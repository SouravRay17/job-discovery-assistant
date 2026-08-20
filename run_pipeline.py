"""
run_pipeline.py — Master orchestrator to run the job fetching and scoring steps in sequence.

Usage:
    python run_pipeline.py
"""

from config import load_config, auto_populate_config
from scraper import run_all_fetchers
from scorer import score_jobs
from tailor import run_batch_tailoring
from email_notifier import send_email_digest
from whatsapp_notifier import notify_top_jobs_whatsapp


def run_pipeline():
    print(f"{'='*60}\nJOB DISCOVERY PIPELINE -- START RUN\n{'='*60}")

    # 1. Load config & auto populate from mapping
    config = auto_populate_config(load_config())

    # 2. Run Fetchers
    print("\n--- STEP 1: FETCHING NEW JOBS ---")
    run_all_fetchers(config)

    # 3. Run Scorer
    print("\n--- STEP 2: SCORING NEW JOBS ---")
    score_jobs()

    # 4. Run Batch Tailoring & Resume Generation
    print("\n--- STEP 3: BATCH TAILORING & LATEX RESUME COMPILATION ---")
    run_batch_tailoring(top_n=10)

    # 5. Send Notifications (Email Digest & WhatsApp)
    print("\n--- STEP 4: SENDING DAILY EMAIL DIGEST & NOTIFICATIONS ---")
    try:
        send_email_digest(top_n=10)
    except Exception as e:
        print(f"  [!] Email notification error: {e}")

    try:
        notify_top_jobs_whatsapp()
    except Exception as e:
        print(f"  [!] WhatsApp notification error: {e}")

    print("\n" + "=" * 60)
    print("JOB DISCOVERY PIPELINE -- COMPLETED RUN")
    print("=" * 60)
    print("Launch the dashboard to review matches and apply:\n  streamlit run dashboard.py\n")


if __name__ == "__main__":
    run_pipeline()
