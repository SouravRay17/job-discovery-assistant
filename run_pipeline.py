"""
run_pipeline.py — Master orchestrator for the Retrieval-First Job Discovery Architecture.

Workflow Execution:
  1. Scrape Jobs (scraper.py) -> Ingests raw listings into jobs.db
  2. Normalize Jobs (normalizer.py) -> Extracts structured metadata & search documents
  3. Index Jobs (indexer.py) -> Updates dense vector embeddings & BM25 keyword index
  4. Hybrid Retrieve (retriever.py) -> Applies hard filters + Vector + BM25 + RRF + deterministic skill scoring -> Top 100
  5. Rerank & Diversify (reranker.py) -> Cross-Encoder deep scoring -> Top 20 -> MMR Diversification -> Top 10
  6. AI Review (scorer.py) -> Gemini qualitative reasoning only on Top 10-20 candidates
  7. Tailor Resumes (tailor.py) -> Generates custom summaries, cover letters, and compiles LaTeX PDFs
  8. Dispatch Notifications (email_notifier.py) -> Sends email digest

Usage:
  python run_pipeline.py
"""

from config import load_config, auto_populate_config
from scraper import run_all_fetchers
from normalizer import normalize_jobs
from indexer import index_jobs
from retriever import retrieve_jobs
from reranker import rerank_jobs
from scorer import score_jobs
from tailor import run_batch_tailoring
from email_notifier import send_email_digest


def run_pipeline():
    print(f"{'='*70}\nJOB DISCOVERY ASSISTANT -- RETRIEVAL-FIRST PIPELINE RUN\n{'='*70}")

    # 1. Load config & auto populate from mapping
    config = auto_populate_config(load_config())

    # 2. Step 1: Scrape Jobs
    print("\n--- STEP 1: SCRAPING NEW JOBS ---")
    try:
        run_all_fetchers(config)
    except Exception as e:
        print(f"  [!] Scraper step warning: {e}")

    # 3. Step 2: Normalize Jobs
    print("\n--- STEP 2: DETERMINISTIC JOB NORMALIZATION & SEARCH DOC GENERATION ---")
    normalize_jobs()

    # 4. Step 3: Index Jobs
    print("\n--- STEP 3: DENSE VECTOR & BM25 INCREMENTAL INDEXING ---")
    index_jobs()

    # 5. Step 4: Hybrid Retrieval
    print("\n--- STEP 4: HYBRID RETRIEVAL (HARD FILTERS + VECTOR + BM25 + RRF) -> TOP 100 ---")
    retrieve_jobs(top_k=100)

    # 6. Step 5: Cross-Encoder Reranking & MMR
    print("\n--- STEP 5: CROSS-ENCODER RERANKING & MMR DIVERSIFICATION -> TOP 10-20 ---")
    rerank_jobs(top_rerank=20, top_diversified=10)

    # 7. Step 6: AI Review (Gemini)
    print("\n--- STEP 6: STRATEGIC AI REVIEW (GEMINI) ON TOP PICKS ONLY ---")
    score_jobs()

    # 8. Step 7: Batch Tailoring & LaTeX PDF Compilation
    print("\n--- STEP 7: RESUME TAILORING & LATEX COMPILATION (TOP 10) ---")
    run_batch_tailoring(top_n=10)

    # 9. Step 8: Multi-channel Notifications
    print("\n--- STEP 8: DISPATCHING EMAIL DIGEST ---")
    try:
        send_email_digest(top_n=10)
    except Exception as e:
        print(f"  [!] Email notification error: {e}")

    print("\n" + "=" * 70)
    print("JOB DISCOVERY PIPELINE -- COMPLETED RUN")
    print("=" * 70)
    print("Launch the interactive review dashboard:\n  streamlit run dashboard.py\n")


if __name__ == "__main__":
    run_pipeline()
