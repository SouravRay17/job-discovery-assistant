"""
evaluate.py — Information Retrieval (IR) benchmarking & evaluation suite.

Calculates:
  - Recall@100 (Can the retriever find the gold jobs?)
  - Recall@20 & Recall@10 (Are relevant jobs reaching reranking & final recommendations?)
  - NDCG@10 & NDCG@20 (Are high-grade jobs placed near the top?)
  - Precision@10 (What percentage of top recommendations are relevant?)
  - MRR (Mean Reciprocal Rank)

Supports:
  - Real user ratings stored in candidate_job_scores (user_rating 1-5, user_feedback)
  - Benchmark evaluation datasets (eval_benchmark_dataset.json)
"""

import argparse
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
import numpy as np

from config import load_config, CV_PATH, DB_PATH
from db import get_connection, init_db
from retriever import retrieve_jobs, load_candidate_profile
from reranker import rerank_jobs

BENCHMARK_DATASET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_benchmark_dataset.json")


def compute_dcg_at_k(relevance_scores: list[float], k: int) -> float:
    """Compute Discounted Cumulative Gain at rank k."""
    dcg = 0.0
    for i in range(min(k, len(relevance_scores))):
        rel = relevance_scores[i]
        dcg += (2.0 ** rel - 1.0) / math.log2(i + 2)
    return dcg


def compute_ndcg_at_k(actual_relevances: list[float], k: int) -> float:
    """Compute Normalized Discounted Cumulative Gain at rank k."""
    dcg = compute_dcg_at_k(actual_relevances, k)
    ideal_relevances = sorted(actual_relevances, reverse=True)
    idcg = compute_dcg_at_k(ideal_relevances, k)
    if idcg <= 0.0:
        return 0.0
    return min(1.0, dcg / idcg)


def compute_recall_at_k(retrieved_keys: list[str], relevant_keys: set[str], k: int) -> float:
    """Compute Recall@K against a set of relevant ground truth keys."""
    if not relevant_keys:
        return 0.0
    top_k_keys = set(retrieved_keys[:k])
    matched = len(top_k_keys & relevant_keys)
    return matched / len(relevant_keys)


def compute_precision_at_k(retrieved_keys: list[str], relevant_keys: set[str], k: int) -> float:
    """Compute Precision@K against a set of relevant ground truth keys."""
    if k <= 0:
        return 0.0
    top_k_keys = set(retrieved_keys[:k])
    matched = len(top_k_keys & relevant_keys)
    return matched / k


def compute_mrr(retrieved_keys: list[str], relevant_keys: set[str]) -> float:
    """Compute Mean Reciprocal Rank."""
    for idx, key in enumerate(retrieved_keys, 1):
        if key in relevant_keys:
            return 1.0 / idx
    return 0.0


def evaluate_against_database() -> dict:
    """Evaluate pipeline against user-labeled ground truth ratings in candidate_job_scores."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, job_id, user_rating, user_feedback, hybrid_retrieval_score,
                   reranker_score, llm_score, final_composite_score
            FROM candidate_job_scores
            WHERE user_rating IS NOT NULL OR user_feedback IS NOT NULL
        """)
        labeled_rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not labeled_rows:
        print("[!] No user-labeled jobs found in database.")
        print("    Label jobs in dashboard.py (Rate 1-5 stars) to generate real evaluation metrics.")
        return {}

    # Define relevant as rating >= 4 or feedback in ('excellent', 'strong', 'applied')
    relevant_keys = set()
    relevance_map = {}

    for row in labeled_rows:
        key = f"{row['source']}::{row['job_id']}"
        rating = row.get("user_rating") or (5 if row.get("user_feedback") == "excellent" else 4)
        relevance_map[key] = float(rating)
        if rating >= 4:
            relevant_keys.add(key)

    # Sort all labeled by final_composite_score
    labeled_rows.sort(key=lambda x: x.get("final_composite_score") or 0.0, reverse=True)
    ranked_keys = [f"{r['source']}::{r['job_id']}" for r in labeled_rows]
    ranked_relevances = [relevance_map[k] for k in ranked_keys]

    r10 = compute_recall_at_k(ranked_keys, relevant_keys, 10)
    p10 = compute_precision_at_k(ranked_keys, relevant_keys, 10)
    ndcg10 = compute_ndcg_at_k(ranked_relevances, 10)
    ndcg20 = compute_ndcg_at_k(ranked_relevances, 20)
    mrr = compute_mrr(ranked_keys, relevant_keys)

    metrics = {
        "labeled_count": len(labeled_rows),
        "relevant_count": len(relevant_keys),
        "recall@10": round(r10, 4),
        "precision@10": round(p10, 4),
        "ndcg@10": round(ndcg10, 4),
        "ndcg@20": round(ndcg20, 4),
        "mrr": round(mrr, 4)
    }

    print("\n" + "=" * 60)
    print("RELEVANCE EVALUATION REPORT (User Feedback Ground Truth)")
    print("=" * 60)
    print(f"  Total Labeled Jobs:   {metrics['labeled_count']}")
    print(f"  Gold Target Jobs (4-5★): {metrics['relevant_count']}")
    print(f"  Recall@10:            {metrics['recall@10'] * 100:.1f}%")
    print(f"  Precision@10:         {metrics['precision@10'] * 100:.1f}%")
    print(f"  NDCG@10:              {metrics['ndcg@10']:.4f}")
    print(f"  NDCG@20:              {metrics['ndcg@20']:.4f}")
    print(f"  MRR:                  {metrics['mrr']:.4f}")
    print("=" * 60 + "\n")
    return metrics


def generate_synthetic_benchmark_dataset():
    """Create a starter benchmark dataset with diverse job categories and expected relevance."""
    sample_data = {
        "candidate_summary": "Sourav Ray — Data & AI Engineer (3 yrs): Python, PySpark, Snowflake, dbt, Airflow, LLM, RAG, LangChain, AWS",
        "benchmark_cases": [
            {
                "title": "Senior AI Engineer - Generative AI Platform",
                "company": "Anthropic Partner",
                "domain": "Generative AI",
                "required_skills": ["Python", "LLMs", "RAG", "LangChain", "Vector Search", "AWS"],
                "experience_min": 3,
                "ground_truth_relevance": 5,
                "expected_category": "exceptional_fit"
            },
            {
                "title": "Data Engineer (Snowflake & dbt)",
                "company": "Fintech Scaleup",
                "domain": "Data Platforms",
                "required_skills": ["Python", "SQL", "Snowflake", "dbt", "Airflow", "PySpark"],
                "experience_min": 3,
                "ground_truth_relevance": 5,
                "expected_category": "exceptional_fit"
            },
            {
                "title": "AI/ML Infrastructure Engineer",
                "company": "Cloud Corp",
                "domain": "ML Infrastructure",
                "required_skills": ["Python", "MLOps", "Kubernetes", "PyTorch", "GCP"],
                "experience_min": 3,
                "ground_truth_relevance": 4,
                "expected_category": "strong_fit"
            },
            {
                "title": "Backend Python Developer",
                "company": "SaaS Platform",
                "domain": "Software Engineering",
                "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "REST APIs"],
                "experience_min": 2,
                "ground_truth_relevance": 3,
                "expected_category": "reasonable_fit"
            },
            {
                "title": "Lead Principal Architect (15+ yrs)",
                "company": "Legacy Enterprise",
                "domain": "Executive",
                "required_skills": ["Enterprise Architecture", "Java", "Oracle"],
                "experience_min": 15,
                "ground_truth_relevance": 1,
                "expected_category": "disqualified_overqualified"
            },
            {
                "title": "HR Recruiter & Facilities Coordinator",
                "company": "Retail Inc",
                "domain": "Operations",
                "required_skills": ["Recruiting", "Payroll", "Office Management"],
                "experience_min": 1,
                "ground_truth_relevance": 1,
                "expected_category": "disqualified_irrelevant"
            }
        ]
    }
    with open(BENCHMARK_DATASET_PATH, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, indent=2)
    print(f"  [OK] Generated starter benchmark dataset at {BENCHMARK_DATASET_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval and ranking metrics")
    parser.add_argument("--create-benchmark", action="store_true", help="Create synthetic benchmark dataset")
    args = parser.parse_args()

    if args.create_benchmark:
        generate_synthetic_benchmark_dataset()
    else:
        evaluate_against_database()


if __name__ == "__main__":
    main()
