"""
whatsapp_notifier.py — Send daily top job discovery matches directly to WhatsApp via CallMeBot webhook.

Usage:
    python whatsapp_notifier.py
"""

import os
import re
import requests
from config import load_config
from db import get_connection


def send_whatsapp(phone: str, api_key: str, message: str) -> bool:
    """Send WhatsApp message using CallMeBot webhook API."""
    url = "https://api.callmebot.com/whatsapp.php"
    params = {"phone": phone, "text": message, "apikey": api_key}
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            print("  [OK] WhatsApp message sent via CallMeBot!")
            return True
        print(f"  [!] CallMeBot returned status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"  [!] CallMeBot request failed: {e}")
    return False


def notify_top_jobs_whatsapp():
    config = load_config()
    wa_config = config.get("whatsapp", {})

    phone = os.getenv("WHATSAPP_PHONE") or wa_config.get("phone", "+917872567781")
    api_key = os.getenv("CALLMEBOT_API_KEY") or wa_config.get("callmebot_api_key", "")
    threshold = config.get("scoring", {}).get("threshold", 70)
    github_repo = os.getenv("GITHUB_REPOSITORY") or "SouravRay17/job-discovery-assistant"

    if not api_key:
        print("  [!] CALLMEBOT_API_KEY missing in config.toml or Environment. Skipping.")
        return

    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url 
            FROM jobs 
            WHERE score >= ? AND status = 'to_review' AND notified_whatsapp = 0
            ORDER BY score DESC LIMIT 10
        """, (threshold,))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[*] No unnotified >=70% job matches found.")
        return

    msg_lines = [
        "🚀 *Job Discovery Assistant — Daily Top Matches*",
        f"Here are your top *{len(rows)}* roles matching >70% with tailored resumes:\n",
    ]

    for idx, (source, job_id, company, title, score, location, url) in enumerate(rows, 1):
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
        pdf_name = f"Sourav_Resume_{company_clean}_{job_id}.pdf"
        github_pdf_url = f"https://github.com/{github_repo}/blob/main/exports/{pdf_name}"

        msg_lines.extend([
            f"*{idx}. {title}*",
            f"🏢 Company: *{company}*",
            f"⭐ Match Score: *{score}/100*",
            f"📍 Location: {location}",
            f"🔗 Apply Link: {url}" if url else "",
            f"📄 Upgraded CV PDF: {github_pdf_url}",
            ""
        ])

    message_text = "\n".join([line for line in msg_lines if line is not None])

    print("\n" + "=" * 60 + "\nSending WhatsApp Notification...\n" + "=" * 60)
    try:
        print(message_text)
    except UnicodeEncodeError:
        print(message_text.encode("utf-8", errors="ignore").decode("ascii", errors="ignore"))

    if send_whatsapp(phone, api_key, message_text):
        conn = get_connection()
        try:
            for (src, jid, _, _, _, _, _) in rows:
                conn.execute("UPDATE jobs SET notified_whatsapp = 1 WHERE source = ? AND id = ?", (src, jid))
            conn.commit()
            print(f"  [OK] Marked {len(rows)} jobs as notified on WhatsApp in jobs.db!")
        finally:
            conn.close()


if __name__ == "__main__":
    notify_top_jobs_whatsapp()
