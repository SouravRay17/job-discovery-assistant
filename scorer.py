"""
scorer.py — Deep qualitative AI review & reasoning on final Top 10-20 candidates using Google Gemini.

Architecture Shift:
  - NO LONGER evaluates every raw scraped listing.
  - Evaluates ONLY the Top 10-20 MMR-diversified candidates selected by retriever.py + reranker.py.
  - Implements caching to eliminate redundant LLM calls.
  - Classifies recommendations into: APPLY, MAYBE, or SKIP with structured justifications.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from config import load_config, CV_PATH, DB_PATH
from db import get_connection, init_db
from retriever import load_candidate_profile

SYSTEM_PROMPT = """You are a Principal Technical Career Strategist and Hiring Committee Evaluator.
You will evaluate the candidate's structured profile against a pre-screened target role.

Evaluate technical synergy, architecture/platform alignment, domain relevance, and potential disqualifiers.
Return ONLY valid JSON matching this exact schema, with no markdown fences and no extra text:
{
  "match_score": <int 0-100>,
  "recommendation": "<APPLY | MAYBE | SKIP>",
  "strengths": ["<strong matching qualification>", ...],
  "missing_skills": ["<unmet requirement or skill gap>", ...],
  "critical_gap": <true if a deal-breaker requirement is missing, else false>,
  "reason": "<2-3 sentence clear, objective strategic justification>"
}"""

MAX_RETRIES = 3
RETRY_DELAY = 2.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_eval_cache_key(candidate_version: str, job_id: str, search_text: str) -> str:
    """Generate deterministic hash key for caching LLM evaluations."""
    raw = f"{candidate_version}::{job_id}::{search_text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def query_scoring_llm(prompt: str, config: dict) -> dict | None:
    """Send evaluation prompt to LLM (Gemini or Ollama), parse and validate JSON."""
    from llm_client import query_llm, parse_json_from_llm

    response_text = query_llm(
        prompt=prompt,
        config=config,
        temperature=0.1,
        max_tokens=1024,
        json_mode=True
    )
    if not response_text:
        return None
    data = parse_json_from_llm(response_text)
    if not data:
        return None

    required_keys = ["match_score", "recommendation", "strengths", "missing_skills", "reason"]
    for key in required_keys:
        if key not in data:
            return None

    try:
        score = int(data["match_score"])
        data["match_score"] = max(0, min(100, score))
    except (ValueError, TypeError):
        return None

    rec = str(data["recommendation"]).upper().strip()
    data["recommendation"] = rec if rec in ("APPLY", "MAYBE", "SKIP") else ("APPLY" if data["match_score"] >= 75 else "MAYBE")

    if not isinstance(data.get("strengths"), list):
        data["strengths"] = [str(data.get("strengths", ""))]
    if not isinstance(data.get("missing_skills"), list):
        data["missing_skills"] = [str(data.get("missing_skills", ""))]
    data["critical_gap"] = bool(data.get("critical_gap", False))

    return data


def score_jobs():
    """Run Gemini AI review on Top 10-20 MMR selected candidates."""
    init_db()
    profile = load_candidate_profile()
    config = load_config()
    candidate_version = profile.get("version", "2.0")

    # Load candidate structured snapshot
    candidate_summary = {
        "name": profile.get("name"),
        "experience_years": profile.get("experience_years"),
        "target_roles": profile.get("target_roles"),
        "core_skills": profile.get("core_skills"),
        "ai_ml_skills": profile.get("ai_ml_skills"),
        "preferred_domains": profile.get("preferred_domains"),
        "education": profile.get("education"),
        "certifications": profile.get("certifications"),
    }

    # Fetch MMR selected candidates from candidate_job_scores joined with jobs
    conn = get_connection()
    try:
        cursor = conn.execute(
            """SELECT c.candidate_id, c.source, c.job_id, c.semantic_score, c.bm25_score,
                      c.required_skill_score, c.role_score, c.experience_score,
                      c.hybrid_retrieval_score, c.reranker_score, c.llm_score, c.ai_reviewed_at,
                      j.company, j.title, j.location, j.remote_type, j.role_family, j.domain,
                      j.required_skills, j.preferred_skills, j.experience_min, j.search_text,
                      j.description_raw, j.url
               FROM candidate_job_scores c
               JOIN jobs j ON c.source = j.source AND c.job_id = j.id
               WHERE c.mmr_selected = 1
               ORDER BY c.reranker_score DESC, c.hybrid_retrieval_score DESC"""
        )
        candidates_to_review = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not candidates_to_review:
        print("[*] No MMR-selected candidates found for AI Review. Run retriever.py and reranker.py first.")
        return

    print(f"\n{'='*60}\nAI Review & Strategic Reasoning (Gemini) -- Processing {len(candidates_to_review)} Roles\n{'='*60}")
    reviewed_count = 0
    skipped_cache_count = 0

    for i, item in enumerate(candidates_to_review, 1):
        source = item["source"]
        job_id = item["job_id"]
        title = item["title"]
        company = item["company"]
        location = item["location"]
        search_text = item["search_text"] or f"{title} at {company}"

        # 1. Check if cached evaluation exists
        if item.get("llm_score") is not None and item.get("ai_reviewed_at") is not None:
            print(f"[{i}/{len(candidates_to_review)}] [CACHED] {title} at {company} -> Score: {item['llm_score']}/100")
            skipped_cache_count += 1
            continue

        print(f"\n[{i}/{len(candidates_to_review)}] [AI REVIEW] {title} at {company} ({location})")
        print(f"     Pre-screen Scores: Hybrid Retrieval={item['hybrid_retrieval_score']} | Cross-Encoder Reranker={item['reranker_score']}")

        # 2. Build High-Signal Evaluation Prompt
        job_metadata = {
            "title": title,
            "company": company,
            "location": location,
            "remote_type": item["remote_type"],
            "role_family": item["role_family"],
            "domain": item["domain"],
            "required_skills": json.loads(item["required_skills"] or "[]"),
            "preferred_skills": json.loads(item["preferred_skills"] or "[]"),
            "experience_required": f"{item['experience_min']}+ years" if item['experience_min'] else "Not specified",
            "url": item["url"],
            "search_summary": search_text
        }

        retrieval_metrics = {
            "semantic_similarity": item["semantic_score"],
            "bm25_keyword_overlap": item["bm25_score"],
            "required_skill_alignment": item["required_skill_score"],
            "role_alignment": item["role_score"],
            "experience_alignment": item["experience_score"],
            "cross_encoder_reranker_score": item["reranker_score"],
        }

        prompt = f"""{SYSTEM_PROMPT}

Candidate Profile Snapshot:
{json.dumps(candidate_summary, indent=2)}

Target Role Metadata:
{json.dumps(job_metadata, indent=2)}

Pre-Computed Alignment Metrics:
{json.dumps(retrieval_metrics, indent=2)}
"""

        # 3. Query LLM with retry
        eval_result = None
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                time.sleep(RETRY_DELAY)
            eval_result = query_scoring_llm(prompt, config)
            if eval_result is not None:
                break

        if eval_result is None:
            print(f"  [!] LLM review failed for {title}. Setting fallback score based on reranker.")
            eval_result = {
                "match_score": int((item["reranker_score"] or 0.8) * 100),
                "recommendation": "APPLY" if (item["reranker_score"] or 0.8) >= 0.75 else "MAYBE",
                "strengths": json.loads(item["required_skills"] or "[]")[:4],
                "missing_skills": [],
                "critical_gap": False,
                "reason": f"Strong alignment identified during hybrid retrieval and cross-encoder evaluation."
            }

        score = eval_result["match_score"]
        recommendation = eval_result["recommendation"]
        reason = eval_result["reason"]
        strengths = json.dumps(eval_result["strengths"])
        missing_skills = json.dumps(eval_result["missing_skills"])
        critical_gap = 1 if eval_result["critical_gap"] else 0

        # Balanced Composite Score: 25% Retrieval + 35% Reranker + 40% LLM Reasoning
        retrieval_part = float(item.get("hybrid_retrieval_score") or 0.7)
        reranker_part = float(item.get("reranker_score") or 0.75)
        llm_part = float(score) / 100.0
        final_composite_score = round(0.25 * retrieval_part + 0.35 * reranker_part + 0.40 * llm_part, 4)

        # 4. Save to candidate_job_scores
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE candidate_job_scores
                   SET llm_score = ?, final_composite_score = ?, recommendation = ?, match_reason = ?,
                       strengths = ?, skill_gaps = ?, critical_gap = ?,
                       status = 'ai_reviewed', ai_reviewed_at = ?
                   WHERE source = ? AND job_id = ?""",
                (score, final_composite_score, recommendation, reason, strengths, missing_skills, critical_gap, now_iso(), source, job_id)
            )
            conn.commit()
        finally:
            conn.close()

        print(f"  -> Match Score: {score}/100 | Blended Final: {int(final_composite_score * 100)}/100 [{recommendation}]")
        print(f"  -> Strategic Reasoning: {reason}")
        reviewed_count += 1
        time.sleep(0.5)

    print(f"\n{'='*60}\nAI Review Complete: Reviewed {reviewed_count} new, Cached {skipped_cache_count}\n{'='*60}\n")


if __name__ == "__main__":
    score_jobs()
