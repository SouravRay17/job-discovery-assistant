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


def run_pipeline(from_step: int = 1, skip_scraping: bool = False):
    print(f"{'='*70}\nJOB DISCOVERY ASSISTANT -- RETRIEVAL-FIRST PIPELINE RUN\n{'='*70}")

    # 1. Load config & auto populate from mapping
    config = auto_populate_config(load_config())

    # Step 1: Scrape Jobs
    if from_step <= 1 and not skip_scraping:
        print("\n--- STEP 1: SCRAPING NEW JOBS ---")
        try:
            run_all_fetchers(config)
        except Exception as e:
            print(f"  [!] Scraper step warning: {e}")
    else:
        print("\n--- STEP 1: SCRAPING SKIPPED ---")

    # Step 2: Normalize Jobs
    if from_step <= 2:
        print("\n--- STEP 2: DETERMINISTIC JOB NORMALIZATION & SEARCH DOC GENERATION ---")
        try:
            normalize_jobs()
        except Exception as e:
            print(f"  [!] Normalizer error: {e}")

    # Step 3: Index Jobs
    if from_step <= 3:
        print("\n--- STEP 3: DENSE VECTOR & BM25 INCREMENTAL INDEXING ---")
        try:
            index_jobs()
        except Exception as e:
            print(f"  [!] Indexing error: {e}")

    # Step 4: Hybrid Retrieval
    if from_step <= 4:
        print("\n--- STEP 4: HYBRID RETRIEVAL (HARD FILTERS + VECTOR + BM25 + RRF) -> TOP 150 ---")
        try:
            retrieve_jobs(top_k=150)
        except Exception as e:
            print(f"  [!] Hybrid retrieval error: {e}")

    # Step 5: Cross-Encoder Reranking & MMR
    if from_step <= 5:
        print("\n--- STEP 5: CROSS-ENCODER RERANKING & MMR DIVERSIFICATION -> TOP 10-20 ---")
        try:
            rerank_jobs(top_rerank=20, top_diversified=10)
        except Exception as e:
            print(f"  [!] Reranking error: {e}")

    # Step 6: AI Review (Gemini)
    if from_step <= 6:
        print("\n--- STEP 6: STRATEGIC AI REVIEW (GEMINI) ON TOP PICKS ONLY ---")
        try:
            score_jobs()
        except Exception as e:
            print(f"  [!] Scorer error: {e}")

    # Step 7: Batch Tailoring & LaTeX PDF Compilation
    if from_step <= 7:
        print("\n--- STEP 7: RESUME TAILORING & LATEX COMPILATION (TOP 10) ---")
        try:
            run_batch_tailoring(top_n=10)
        except Exception as e:
            print(f"  [!] Tailoring error: {e}")

    # Step 8: Multi-channel Notifications
    if from_step <= 8:
        print("\n--- STEP 8: DISPATCHING EMAIL DIGEST ---")
        try:
            send_email_digest(top_n=10)
        except Exception as e:
            print(f"  [!] Email notification error: {e}")

    print("\n" + "=" * 70)
    print("JOB DISCOVERY PIPELINE -- COMPLETED RUN")
    print("=" * 70)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run Job Discovery retrieval pipeline")
    parser.add_argument("--from-step", type=int, default=1, choices=range(1, 9), help="Start from specific step (1-8)")
    parser.add_argument("--skip-scraping", action="store_true", help="Skip scraping and start from normalization")
    args = parser.parse_args()

    run_pipeline(from_step=args.from_step, skip_scraping=args.skip_scraping)


if __name__ == "__main__":
    main()
