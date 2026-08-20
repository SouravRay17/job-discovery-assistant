"""
retriever.py — High-precision hybrid retrieval engine (Vector + BM25 + RRF + Deterministic Scoring).

Pipeline:
  1. Load Candidate Profile & generate candidate query & embedding
  2. Apply Hard Filters (Experience ceiling, Location, Excluded roles)
  3. Dense Vector Search (Cosine Similarity)
  4. BM25 Keyword Search (Exact Skill & Title Matching)
  5. Reciprocal Rank Fusion (RRF)
  6. Deterministic Skill & Experience Alignment Scoring
  7. Composite Hybrid Scoring -> Produces Top 100 in candidate_job_scores table.

ZERO LLM calls during retrieval.
"""

import json
import os
import pickle
import re
from datetime import datetime, timezone
import numpy as np

from config import load_config, CV_PATH
from db import get_connection, init_db
from indexer import (
    compute_embeddings, tokenize_for_bm25,
    EMBEDDING_FILE, JOB_MAP_FILE, BM25_FILE
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_candidate_profile() -> dict:
    """Load candidate profile from cv_profile.json."""
    if not os.path.exists(CV_PATH):
        raise FileNotFoundError(f"Candidate profile not found at {CV_PATH}")
    with open(CV_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_candidate_search_text(profile: dict) -> str:
    """Construct high-signal candidate query representation."""
    target_roles = ", ".join(profile.get("target_roles", []))
    core_skills = ", ".join(profile.get("core_skills", []))
    ai_skills = ", ".join(profile.get("ai_ml_skills", []))
    secondary = ", ".join(profile.get("secondary_skills", []))
    domains = ", ".join(profile.get("preferred_domains", []))
    exp = profile.get("experience_years", 3)

    return f"""Target Roles: {target_roles}
Core Skills: {core_skills}
AI & ML Skills: {ai_skills}
Secondary Skills: {secondary}
Experience: {exp}+ years in Data & AI Engineering
Domains: {domains}"""


def check_hard_filters(job: dict, profile: dict) -> tuple[bool, str | None]:
    """
    Deterministic hard constraints elimination.
    Returns (True, None) if eligible, or (False, rejection_reason).
    """
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    exp_min = job.get("experience_min")
    candidate_exp = profile.get("experience_years", 3)

    # 1. Experience Ceiling Filter: Eliminate jobs requiring >= (candidate_exp + 3.0) years
    if exp_min is not None and exp_min > (candidate_exp + 3.0):
        return False, f"Requires {int(exp_min)}+ yrs (candidate has {candidate_exp} yrs)"

    # 2. Excluded Roles Filter
    excluded = profile.get("excluded_roles", [])
    for exc in excluded:
        exc_clean = exc.lower().strip()
        if exc_clean and exc_clean in title:
            return False, f"Matches excluded role keyword '{exc}'"

    # 3. Location / Remote Compatibility Filter
    target_locations = [loc.lower().strip() for loc in profile.get("preferred_locations", ["remote", "india"])]
    is_remote = bool(job.get("remote")) or any(k in location for k in ("remote", "anywhere", "worldwide", "global"))

    if not is_remote:
        # Check if job is in acceptable country/cities
        matched_loc = any(re.search(r'\b' + re.escape(t) + r'\b', location) for t in target_locations if t != "remote")
        if not matched_loc:
            # Foreign on-site filters
            foreign_kws = ["us", "united states", "usa", "uk", "united kingdom", "canada", "germany", "france", "poland", "london"]
            if any(re.search(r'\b' + kw + r'\b', location) for kw in foreign_kws):
                return False, f"Foreign on-site location ({job.get('location')})"

    return True, None


def compute_skill_overlap(candidate_skills_set: set[str], job_skills: list[str]) -> float:
    """Calculate overlap percentage between job skills and candidate skills."""
    if not job_skills:
        return 0.8  # Neutral score if no specific skills specified

    matched = 0
    for js in job_skills:
        js_lower = js.lower()
        if any(js_lower in cs.lower() or cs.lower() in js_lower for cs in candidate_skills_set):
            matched += 1

    return min(1.0, matched / len(job_skills))


def compute_role_score(job_title: str, job_role: str, target_roles: list[str]) -> float:
    """Calculate similarity of job title and role family to target roles."""
    text = f"{job_title} {job_role}".lower()
    score = 0.0
    for target in target_roles:
        t_clean = target.lower().strip()
        if t_clean in text:
            return 1.0
        words = t_clean.split()
        if len(words) > 1 and all(w in text for w in words):
            return 0.95
        overlap = sum(1 for w in words if w in text and len(w) > 2)
        if overlap > 0:
            score = max(score, overlap / len(words) * 0.8)
    return score if score > 0 else 0.4


def compute_domain_score(job_domain: str, preferred_domains: list[str]) -> float:
    """Score alignment with candidate preferred career domains."""
    if not job_domain or not preferred_domains:
        return 0.7
    job_d = job_domain.lower()
    for pref in preferred_domains:
        p_clean = pref.lower()
        if p_clean in job_d or job_d in p_clean:
            return 1.0
    return 0.5


def compute_experience_score(exp_min: float | None, exp_max: float | None, candidate_exp: float) -> float:
    """Score candidate experience fit against job requirements."""
    if exp_min is None:
        return 0.95  # No restriction stated

    if exp_min <= candidate_exp:
        if exp_max is None or candidate_exp <= exp_max:
            return 1.0
        else:
            # Slight overqualification penalty
            return max(0.8, 1.0 - (candidate_exp - exp_max) * 0.05)
    else:
        # Underqualification penalty
        diff = exp_min - candidate_exp
        return max(0.0, 1.0 - (diff * 0.25))


def retrieve_jobs(top_k: int = 100) -> list[dict]:
    """Execute hybrid retrieval over indexed jobs to produce top candidate matches."""
    init_db()
    profile = load_candidate_profile()
    candidate_id = profile.get("contact", {}).get("email", "default")
    candidate_version = profile.get("version", "2.0")
    candidate_exp = profile.get("experience_years", 3)

    # All candidate skills normalized into a search set
    all_candidate_skills = set(
        profile.get("core_skills", []) +
        profile.get("ai_ml_skills", []) +
        profile.get("secondary_skills", [])
    )

    # 1. Fetch all indexed jobs from database
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT source, id, title, company, location, remote, url, "
            "search_text, required_skills, preferred_skills, role_family, domain, "
            "experience_min, experience_max, date_posted FROM jobs WHERE normalized_at IS NOT NULL"
        )
        jobs = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not jobs:
        print("[*] No indexed jobs found. Run normalizer.py and indexer.py first.")
        return []

    print(f"\n{'='*60}\nHybrid Retriever -- Evaluating {len(jobs)} Total Jobs\n{'='*60}")

    # 2. Hard Filters
    eligible_jobs = []
    filtered_out_count = 0
    for job in jobs:
        passed, reason = check_hard_filters(job, profile)
        if passed:
            eligible_jobs.append(job)
        else:
            filtered_out_count += 1

    print(f"  [1/5] Hard Filters Applied: Kept {len(eligible_jobs)}, Eliminated {filtered_out_count} non-compliant jobs.")
    if not eligible_jobs:
        print("[!] No jobs passed hard constraints.")
        return []

    # 3. Vector Search
    candidate_query = build_candidate_search_text(profile)
    candidate_vector = compute_embeddings([candidate_query])[0]

    job_vectors = {}
    if os.path.exists(EMBEDDING_FILE) and os.path.exists(JOB_MAP_FILE):
        try:
            data = np.load(EMBEDDING_FILE)
            with open(JOB_MAP_FILE, "r", encoding="utf-8") as f:
                key_map = json.load(f)
            matrix = data["embeddings"]
            for idx, k in enumerate(key_map):
                job_vectors[k] = matrix[idx]
        except Exception:
            pass

    # Compute dense cosine similarities
    vector_scores = {}
    for job in eligible_jobs:
        key = f"{job['source']}::{job['id']}"
        vec = job_vectors.get(key)
        if vec is not None:
            # Cosine similarity (both vectors are normalized)
            sim = float(np.dot(candidate_vector, vec))
            vector_scores[key] = max(0.0, min(1.0, (sim + 1.0) / 2.0))  # Scale to 0..1
        else:
            vector_scores[key] = 0.5

    # 4. BM25 Search
    bm25_scores = {}
    if os.path.exists(BM25_FILE):
        try:
            with open(BM25_FILE, "rb") as f:
                bm25_data = pickle.load(f)
            bm25_model = bm25_data["model"]
            bm25_keys = bm25_data["keys"]

            query_tokens = tokenize_for_bm25(
                f"{' '.join(profile.get('target_roles', []))} {' '.join(profile.get('core_skills', []))} "
                f"{' '.join(profile.get('ai_ml_skills', []))} {' '.join(profile.get('preferred_domains', []))}"
            )
            raw_bm25 = bm25_model.get_scores(query_tokens)
            max_bm25 = max(raw_bm25) if len(raw_bm25) > 0 and max(raw_bm25) > 0 else 1.0

            for k, score in zip(bm25_keys, raw_bm25):
                bm25_scores[k] = float(score / max_bm25)
        except Exception as e:
            print(f"  [!] BM25 search fallback: {e}")

    # Rank sorting for RRF
    sorted_by_vec = sorted(eligible_jobs, key=lambda j: vector_scores.get(f"{j['source']}::{j['id']}", 0.0), reverse=True)
    sorted_by_bm25 = sorted(eligible_jobs, key=lambda j: bm25_scores.get(f"{j['source']}::{j['id']}", 0.0), reverse=True)

    vec_ranks = {f"{j['source']}::{j['id']}": rank + 1 for rank, j in enumerate(sorted_by_vec)}
    bm25_ranks = {f"{j['source']}::{j['id']}": rank + 1 for rank, j in enumerate(sorted_by_bm25)}

    # 5. Composite Scoring & RRF
    print(f"  [2/5] Performing Dense Vector + BM25 Reciprocal Rank Fusion...")
    scored_candidates = []

    for job in eligible_jobs:
        key = f"{job['source']}::{job['id']}"
        v_score = vector_scores.get(key, 0.5)
        b_score = bm25_scores.get(key, 0.0)

        # RRF formula (constant k = 60)
        v_rank = vec_ranks.get(key, len(eligible_jobs))
        b_rank = bm25_ranks.get(key, len(eligible_jobs))
        rrf = (1.0 / (60.0 + v_rank)) + (1.0 / (60.0 + b_rank))

        # Deterministic Skills & Role Alignment
        req_skills = json.loads(job.get("required_skills") or "[]")
        pref_skills = json.loads(job.get("preferred_skills") or "[]")
        req_skill_score = compute_skill_overlap(all_candidate_skills, req_skills)
        pref_skill_score = compute_skill_overlap(all_candidate_skills, pref_skills)
        role_score = compute_role_score(job.get("title", ""), job.get("role_family", ""), profile.get("target_roles", []))
        domain_score = compute_domain_score(job.get("domain", ""), profile.get("preferred_domains", []))
        exp_score = compute_experience_score(job.get("experience_min"), job.get("experience_max"), candidate_exp)

        # Refined Hybrid Composite Formula:
        # 25% Vector + 15% BM25 + 20% Role Intent/Trajectory + 10% Domain Fit + 20% Required Skills + 5% Preferred Skills + 5% Experience
        hybrid_retrieval_score = (
            0.25 * v_score +
            0.15 * b_score +
            0.20 * role_score +
            0.10 * domain_score +
            0.20 * req_skill_score +
            0.05 * pref_skill_score +
            0.05 * exp_score
        )

        scored_candidates.append({
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "source": job["source"],
            "job_id": job["id"],
            "company": job["company"],
            "title": job["title"],
            "location": job["location"],
            "semantic_score": round(v_score, 4),
            "bm25_score": round(b_score, 4),
            "required_skill_score": round(req_skill_score, 4),
            "preferred_skill_score": round(pref_skill_score, 4),
            "role_score": round(role_score, 4),
            "experience_score": round(exp_score, 4),
            "hybrid_retrieval_score": round(hybrid_retrieval_score, 4),
        })

    # Sort descending by hybrid_retrieval_score and truncate to top_k (Top 100)
    scored_candidates.sort(key=lambda x: x["hybrid_retrieval_score"], reverse=True)
    top_results = scored_candidates[:top_k]

    print(f"  [3/5] Top {len(top_results)} matches retrieved (Highest score: {top_results[0]['hybrid_retrieval_score'] if top_results else 0})")

    # 6. Save Top 100 into candidate_job_scores table
    print(f"  [4/5] Writing Top {len(top_results)} candidates into candidate_job_scores table...")
    conn = get_connection()
    try:
        now_str = now_iso()
        for item in top_results:
            conn.execute(
                """INSERT INTO candidate_job_scores
                   (candidate_id, candidate_version, source, job_id,
                    semantic_score, bm25_score, required_skill_score, preferred_skill_score,
                    role_score, experience_score, hybrid_retrieval_score, status, retrieved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'retrieved', ?)
                   ON CONFLICT(candidate_id, source, job_id) DO UPDATE SET
                    semantic_score = excluded.semantic_score,
                    bm25_score = excluded.bm25_score,
                    required_skill_score = excluded.required_skill_score,
                    preferred_skill_score = excluded.preferred_skill_score,
                    role_score = excluded.role_score,
                    experience_score = excluded.experience_score,
                    hybrid_retrieval_score = excluded.hybrid_retrieval_score,
                    status = 'retrieved',
                    retrieved_at = excluded.retrieved_at""",
                (
                    item["candidate_id"], item["candidate_version"], item["source"], item["job_id"],
                    item["semantic_score"], item["bm25_score"], item["required_skill_score"],
                    item["preferred_skill_score"], item["role_score"], item["experience_score"],
                    item["hybrid_retrieval_score"], now_str
                )
            )
        conn.commit()
    finally:
        conn.close()

    print(f"  [5/5] [OK] Successfully completed hybrid retrieval!\n")
    return top_results


if __name__ == "__main__":
    retrieve_jobs(top_k=100)
