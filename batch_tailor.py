"""
batch_tailor.py — Batch generate tailored summaries, cover letters, and LaTeX PDF resumes
for ALL qualified jobs in jobs.db above the scoring threshold.

Usage:
    python batch_tailor.py              # Tailor ALL qualifying jobs in DB
    python batch_tailor.py --top 10     # Tailor top N jobs only (optional)
"""

import argparse
import os
import sqlite3
import sys
import yaml
from db import get_connection
import tailor

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_batch_tailoring(top_n: int | None = 10):
    config = load_config()
    threshold = config.get("scoring", {}).get("threshold", 60)
    
    # Clean up old files in exports directory to ensure we only have fresh resumes
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")
    if os.path.exists(exports_dir):
        import glob
        for old_file in glob.glob(os.path.join(exports_dir, "*")):
            try:
                if os.path.isfile(old_file):
                    os.remove(old_file)
            except Exception as e:
                print(f"  [!] Error cleaning up old file {old_file}: {e}")
    else:
        os.makedirs(exports_dir, exist_ok=True)

    conn = get_connection()
    try:
        query = """
            SELECT source, id, company, title, score, location, remote, url, tailored_summary
            FROM jobs 
            WHERE score >= ? AND status != 'rejected'
            ORDER BY score DESC
        """
        params = [threshold]
        if top_n:
            query += " LIMIT ?"
            params.append(top_n)
            
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"[*] No jobs found with score >= {threshold}.")
        return

    total_jobs = len(rows)
    print(f"\n{'='*60}")
    print(f"Batch Tailoring -- Processing {total_jobs} Qualifying Openings")
    print(f"{'='*60}")

    tailored_count = 0
    pdf_count = 0

    for idx, row in enumerate(rows, 1):
        source, job_id, company, title, score, location, remote, url, existing_summary = row
        print(f"\n[{idx}/{total_jobs}] [{score}/100] {company} — {title} ({location})")

        # 1. Tailor summary & cover letter if missing
        if not existing_summary:
            print("  * Generating tailored summary and cover letter via Ollama...")
            config, cv_profile = tailor.validate_environment()
            result = tailor.tailor_job(source, job_id, config, cv_profile)
            if result:
                tailored_count += 1
            else:
                print("  [!] Failed to generate tailoring text. Skipping PDF compilation.")
                continue
        else:
            print("  * Tailored text already present in DB.")

        # 2. Compile custom LaTeX PDF resume
        print("  * Compiling LaTeX resume PDF via Tectonic...")
        pdf_path = tailor.compile_pdf_resume(source, job_id)
        if pdf_path:
            pdf_count += 1
            print(f"  [OK] PDF ready: {os.path.basename(pdf_path)}")
        else:
            print("  [!] PDF compilation failed for this listing.")

    print(f"\n{'='*60}")
    print(f"Batch Tailoring Complete!")
    print(f"Processed: {total_jobs} jobs | New Summaries: {tailored_count} | PDFs Generated: {pdf_count}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch tailor application materials for qualifying jobs.")
    parser.add_argument("--top", type=int, default=None, help="Optional limit to top N jobs")
    args = parser.parse_args()

    run_batch_tailoring(top_n=args.top)
