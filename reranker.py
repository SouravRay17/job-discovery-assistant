"""
reranker.py — Deep Cross-Encoder reranker and MMR diversification engine.

Pipeline:
  1. Load Top 100 retrieved jobs from candidate_job_scores
  2. Cross-Encoder Deep Scoring -> Evaluates (candidate_profile, job_search_text) -> Top 20
  3. MMR (Maximal Marginal Relevance) Diversification -> Eliminates company/role clustering -> Top 10
  4. Updates candidate_job_scores with reranker_score, mmr_selected, and reranked_at.
"""

import json
import os
import re
from datetime import datetime, timezone
import numpy as np

from config import load_config
from db import get_connection, init_db
from retriever import load_candidate_profile, build_candidate_search_text
from indexer import EMBEDDING_FILE, JOB_MAP_FILE

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_cross_encoder_instance = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_cross_encoder():
    """Lazy load CrossEncoder model for deep pairwise ranking."""
    global _cross_encoder_instance
    if _cross_encoder_instance is None:
        try:
            from sentence_transformers import CrossEncoder
            print(f"  [*] Loading Cross-Encoder: {DEFAULT_RERANKER_MODEL}...")
            _cross_encoder_instance = CrossEncoder(DEFAULT_RERANKER_MODEL, max_length=512)
        except Exception as e:
            print(f"  [!] CrossEncoder not available ({e}). Using feature-weighted reranker fallback.")
            _cross_encoder_instance = None
    return _cross_encoder_instance


def compute_cross_encoder_scores(pairs: list[tuple[str, str]]) -> list[float]:
    """Score (query, document) pairs using CrossEncoder with sigmoid normalization."""
    model = get_cross_encoder()
    if model is not None:
        raw_scores = model.predict(pairs, show_progress_bar=False)
        # Apply sigmoid to map unbounded logits to 0..1
        sigmoid_scores = 1.0 / (1.0 + np.exp(-np.array(raw_scores, dtype=np.float32)))
        return [round(float(s), 4) for s in sigmoid_scores]

    # Fallback: cross-feature deep interaction heuristic
    scores = []
    for query, doc in pairs:
        q_words = set(re.findall(r"\w+", query.lower()))
        d_words = set(re.findall(r"\w+", doc.lower()))
        overlap = len(q_words & d_words)
        score = min(1.0, overlap / (len(q_words) * 0.75))
        scores.append(round(score, 4))
    return scores


def apply_mmr_diversification(
    candidates: list[dict],
    embeddings_map: dict,
    top_n: int = 10,
    diversity_weight: float = 0.7,
    max_per_company: int = 2
) -> list[dict]:
    """
    Maximal Marginal Relevance (MMR) Diversification.
    Selects top diverse subset balancing relevance score with embedding distance
    and company diversity limits.
    """
    if not candidates or len(candidates) <= top_n:
        return candidates

    selected = []
    selected_keys = set()
    company_counts = {}

    # Pool of candidates
    unselected = list(candidates)

    while len(selected) < top_n and unselected:
        best_idx = -1
        best_mmr_score = -float("inf")

        for idx, cand in enumerate(unselected):
            key = f"{cand['source']}::{cand['job_id']}"
            company = cand.get("company", "Unknown")

            # Enforce max per company constraint
            if company_counts.get(company, 0) >= max_per_company:
                continue

            rel_score = cand.get("reranker_score", cand.get("hybrid_retrieval_score", 0.5))
            cand_vec = embeddings_map.get(key)

            if not selected or cand_vec is None:
                max_sim = 0.0
            else:
                sims = []
                for s in selected:
                    s_key = f"{s['source']}::{s['job_id']}"
                    s_vec = embeddings_map.get(s_key)
                    if s_vec is not None and cand_vec is not None:
                        sim = float(np.dot(cand_vec, s_vec))
                        sims.append(sim)
                max_sim = max(sims) if sims else 0.0

            # MMR formula
            mmr = diversity_weight * rel_score - (1.0 - diversity_weight) * max_sim

            if mmr > best_mmr_score:
                best_mmr_score = mmr
                best_idx = idx

        if best_idx == -1:
            # If all remaining hit company caps, relax constraint
            if unselected:
                cand = unselected.pop(0)
                selected.append(cand)
            break

        chosen = unselected.pop(best_idx)
        selected.append(chosen)
        company_counts[chosen.get("company", "Unknown")] = company_counts.get(chosen.get("company", "Unknown"), 0) + 1

    return selected


def rerank_jobs(top_rerank: int = 20, top_diversified: int = 10) -> list[dict]:
    """Rerank retrieved candidates with Cross-Encoder and apply MMR diversification."""
    init_db()
    profile = load_candidate_profile()
    candidate_query = build_candidate_search_text(profile)

    # 1. Load Top 100 from candidate_job_scores joined with jobs search_text
    conn = get_connection()
    try:
        cursor = conn.execute(
            """SELECT c.candidate_id, c.source, c.job_id, c.hybrid_retrieval_score,
                      j.company, j.title, j.location, j.search_text, j.role_family, j.domain
               FROM candidate_job_scores c
               JOIN jobs j ON c.source = j.source AND c.job_id = j.id
               WHERE c.status = 'retrieved' OR c.reranker_score IS NULL
               ORDER BY c.hybrid_retrieval_score DESC LIMIT 100"""
        )
        retrieved = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not retrieved:
        print("[*] No retrieved jobs to rerank. Run retriever.py first.")
        return []

    print(f"\n{'='*60}\nReranker & Diversification -- Processing {len(retrieved)} Retrieved Candidates\n{'='*60}")

    # 2. Pairwise Cross-Encoder Inference
    pairs = [(candidate_query, item["search_text"] or f"{item['title']} at {item['company']}") for item in retrieved]
    print(f"  [1/3] Computing Cross-Encoder deep pairwise relevance for {len(pairs)} jobs...")
    reranker_scores = compute_cross_encoder_scores(pairs)

    for item, score in zip(retrieved, reranker_scores):
        item["reranker_score"] = score

    # Sort descending by reranker_score and select Top 20 for diversification
    retrieved.sort(key=lambda x: x["reranker_score"], reverse=True)
    top_20 = retrieved[:top_rerank]
    print(f"  [2/3] Top {len(top_20)} candidates selected by Cross-Encoder (Scores: {top_20[0]['reranker_score'] if top_20 else 0} to {top_20[-1]['reranker_score'] if top_20 else 0})")

    # 3. Load embeddings for MMR
    embeddings_map = {}
    if os.path.exists(EMBEDDING_FILE) and os.path.exists(JOB_MAP_FILE):
        try:
            data = np.load(EMBEDDING_FILE)
            with open(JOB_MAP_FILE, "r", encoding="utf-8") as f:
                key_map = json.load(f)
            matrix = data["embeddings"]
            for idx, k in enumerate(key_map):
                embeddings_map[k] = matrix[idx]
        except Exception:
            pass

    # 4. Apply MMR Diversification
    print(f"  [3/3] Applying MMR Diversification across companies and role families (target: Top {top_diversified})...")
    final_diverse_top = apply_mmr_diversification(
        candidates=top_20,
        embeddings_map=embeddings_map,
        top_n=top_diversified,
        diversity_weight=0.75,
        max_per_company=2
    )

    diverse_keys = {f"{item['source']}::{item['job_id']}" for item in final_diverse_top}

    # 5. Persist Reranking & MMR flags back to candidate_job_scores
    conn = get_connection()
    try:
        now_str = now_iso()
        # Reset previous mmr_selected
        conn.execute("UPDATE candidate_job_scores SET mmr_selected = 0")

        for item in retrieved:
            is_mmr = 1 if f"{item['source']}::{item['job_id']}" in diverse_keys else 0
            conn.execute(
                """UPDATE candidate_job_scores
                   SET reranker_score = ?, mmr_selected = ?, status = 'reranked', reranked_at = ?
                   WHERE source = ? AND job_id = ?""",
                (item["reranker_score"], is_mmr, now_str, item["source"], item["job_id"])
            )
        conn.commit()
    finally:
        conn.close()

    print(f"\n[OK] Reranking complete! {len(final_diverse_top)} high-signal diverse openings flagged for Gemini Review.\n")
    return final_diverse_top


if __name__ == "__main__":
    rerank_jobs()
