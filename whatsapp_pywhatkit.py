"""
whatsapp_pywhatkit.py — Send daily top job matches and tailored resume PDF links to WhatsApp using pywhatkit.

Each entry includes:
  - Job Role Name
  - Company Name
  - Match Score (>70%)
  - Direct Apply Link
  - Path to Upgraded Tailored Resume PDF

Usage:
    python whatsapp_pywhatkit.py
"""

import os
import re
import sqlite3
import sys
import yaml
from db import get_connection
import tailor

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

def send_pywhatkit_whatsapp(phone: str, message: str) -> bool:
    """Send message instantly using pywhatkit."""
    try:
        import pywhatkit
        print(f"  * Dispatching WhatsApp message via PyWhatKit to {phone}...")
        pywhatkit.sendwhatmsg_instantly(
            phone_no=phone,
            message=message,
            wait_time=15,
            tab_close=True,
            close_time=3
        )
        print("  [OK] WhatsApp message dispatched via PyWhatKit!")
        return True
    except Exception as e:
        print(f"  [!] PyWhatKit dispatch error: {e}")
        return False

def send_pywhatkit_digest(top_n: int = 10):
    config = load_config()
    phone = config.get("whatsapp", {}).get("phone", "+917872567781")
    threshold = config.get("scoring", {}).get("threshold", 70)

    # 1. Query top matches from DB that haven't been notified on WhatsApp yet
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url, tailored_summary
            FROM jobs
            WHERE score >= ? 
              AND status = 'to_review'
              AND notified_whatsapp = 0
            ORDER BY score DESC
            LIMIT ?
        """, (threshold, top_n))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"[*] No jobs matching >= {threshold}% found to send via PyWhatKit.")
        return

    print(f"\n{'='*60}")
    print(f"PyWhatKit WhatsApp Digest -- Preparing {len(rows)} Top Roles")
    print(f"{'='*60}")

    msg_lines = [
        "🚀 *Job Discovery Assistant — Daily Top Matches & Tailored Resumes*",
        f"Here are your top *{len(rows)}* job matches (>70% score) with tailored resumes:\n"
    ]

    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")

    for idx, (source, job_id, company, title, score, location, url, tailored_summary) in enumerate(rows, 1):
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
        pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}.pdf")

        # Compile PDF if missing
        if not os.path.exists(pdf_path):
            print(f"  * PDF missing for {company} — compiling...")
            pdf_path = tailor.compile_pdf_resume(source, job_id) or pdf_path

        msg_lines.append(f"*{idx}. {title}*")
        msg_lines.append(f"🏢 Company: *{company}*")
        msg_lines.append(f"⭐ Match Score: *{score}/100*")
        msg_lines.append(f"📍 Location: {location}")
        if url:
            msg_lines.append(f"🔗 Apply Link: {url}")
        if pdf_path and os.path.exists(pdf_path):
            msg_lines.append(f"📄 Upgraded CV: {os.path.basename(pdf_path)}")
        msg_lines.append("")

    msg_lines.append("Open the links to apply and attach your upgraded CV from `exports/`!")
    full_message = "\n".join(msg_lines)

    print("\nFormatted Message Preview:")
    print("-" * 50)
    try:
        print(full_message)
    except UnicodeEncodeError:
        print(full_message.encode("utf-8", errors="ignore").decode("ascii", errors="ignore"))
    print("-" * 50 + "\n")

    # Dispatch via PyWhatKit
    success = send_pywhatkit_whatsapp(phone, full_message)
    if success:
        conn = get_connection()
        try:
            for (src, jid, _, _, _, _, _, _) in rows:
                conn.execute(
                    "UPDATE jobs SET notified_whatsapp = 1 WHERE source = ? AND id = ?",
                    (src, jid)
                )
            conn.commit()
            print(f"  [OK] Marked {len(rows)} jobs as notified on WhatsApp (pywhatkit) in jobs.db!")
        finally:
            conn.close()

if __name__ == "__main__":
    send_pywhatkit_digest(top_n=10)
