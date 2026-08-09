"""
run_pipeline.py — Master orchestrator to run the job fetching and scoring steps in sequence.

Usage:
    python run_pipeline.py
"""

from scraper import load_config, run_all_fetchers, auto_populate_config
from scorer import score_jobs
from batch_tailor import run_batch_tailoring


def run_pipeline():
    print(f"{'='*60}")
    print("JOB DISCOVERY PIPELINE -- START RUN")
    print(f"{'='*60}")

    # 1. Load config & auto populate from mapping
    config = load_config()
    config = auto_populate_config(config)

    # 2. Run Fetchers
    print("\n--- STEP 1: FETCHING NEW JOBS ---")
    run_all_fetchers(config)

    # 3. Run Scorer
    print("\n--- STEP 2: SCORING NEW JOBS ---")
    score_jobs()

    # 4. Run Batch Tailoring & Resume Generation (only for the top 10 matched jobs)
    print("\n--- STEP 3: BATCH TAILORING & LATEX RESUME COMPILATION ---")
    run_batch_tailoring(top_n=10)

    # 5. Send Notifications (Email Digest & WhatsApp)
    print("\n--- STEP 4: SENDING DAILY EMAIL DIGEST & NOTIFICATIONS ---")
    try:
        from email_notifier import send_email_digest
        send_email_digest(top_n=10)
    except Exception as e:
        print(f"  [!] Email notification error: {e}")

    try:
        from whatsapp_notifier import notify_top_jobs_whatsapp
        notify_top_jobs_whatsapp()
    except Exception as e:
        print(f"  [!] WhatsApp notification error: {e}")

    print("\n" + "="*60)
    print("JOB DISCOVERY PIPELINE -- COMPLETED RUN")
    print("="*60)
    print("Launch the dashboard to review matches and apply:")
    print("  streamlit run dashboard.py\n")


if __name__ == "__main__":
    run_pipeline()
