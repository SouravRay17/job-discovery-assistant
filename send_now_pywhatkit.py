"""
send_now_pywhatkit.py — Instant WhatsApp dispatch with current India local timestamp using PyWhatKit.
"""

import os
import re
import sys
import time
import yaml
from datetime import datetime, timezone, timedelta
from db import get_connection

# Calculate current IST time (UTC+5:30)
ist_tz = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist_tz).strftime("%I:%M %p IST on %d %b %Y")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

def send_now():
    config = load_config()
    phone = config.get("whatsapp", {}).get("phone", "+917872567781")
    threshold = config.get("scoring", {}).get("threshold", 70)

    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url
            FROM jobs
            WHERE score >= ? AND status != 'rejected'
            ORDER BY score DESC
            LIMIT 10
        """, (threshold,))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[*] No >=70% job matches found.")
        return

    msg_lines = [
        f"🚀 *Job Discovery Assistant — Live Alert*",
        f"🕒 Timestamp: *{now_ist}*",
        f"Here are your top *{len(rows)}* job matches (>70% score) with tailored resumes:\n"
    ]

    github_repo = "SouravRay17/job-discovery-assistant"

    for idx, (source, job_id, company, title, score, location, url) in enumerate(rows, 1):
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
        pdf_name = f"Sourav_Resume_{company_clean}_{job_id}.pdf"
        github_pdf_url = f"https://github.com/{github_repo}/blob/main/exports/{pdf_name}"

        msg_lines.append(f"*{idx}. {title}*")
        msg_lines.append(f"🏢 Company: *{company}*")
        msg_lines.append(f"⭐ Match Score: *{score}/100*")
        msg_lines.append(f"📍 Location: {location}")
        if url:
            msg_lines.append(f"🔗 Apply Link: {url}")
        msg_lines.append(f"📄 Upgraded CV PDF: {github_pdf_url}")
        msg_lines.append("")

    msg_lines.append("Open the links to apply and attach your upgraded CV!")
    full_message = "\n".join(msg_lines)

    print(f"\n{'='*60}")
    print(f"Sending Instant WhatsApp Alert at {now_ist} to {phone}")
    print(f"{'='*60}")
    try:
        print(full_message)
    except UnicodeEncodeError:
        print(full_message.encode("utf-8", errors="ignore").decode("ascii", errors="ignore"))
    print(f"{'='*60}\n")

    import pywhatkit
    import pyautogui

    print("  * Opening WhatsApp Web tab in Chrome...")
    # Open WhatsApp Web send URL
    pywhatkit.sendwhatmsg_instantly(
        phone_no=phone,
        message=full_message,
        wait_time=20,
        tab_close=False
    )
    
    # Give browser extra 3 seconds to focus chat box and press enter
    time.sleep(3)
    pyautogui.press("enter")
    print("  [OK] Pressed ENTER to send message on WhatsApp Web!")

if __name__ == "__main__":
    send_now()
