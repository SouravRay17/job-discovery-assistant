"""
whatsapp_notifier.py — Send daily job discovery updates directly to WhatsApp.

Supports:
  1. CallMeBot (100% Free, simple API key setup)
  2. Twilio WhatsApp API (Enterprise API)

Usage:
    python whatsapp_notifier.py             # Send WhatsApp update for top >=70% matches
"""

import os
import sqlite3
import requests
import yaml
from db import get_connection

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

def send_whatsapp_callmebot(phone: str, api_key: str, message: str) -> bool:
    """Send WhatsApp message using CallMeBot free API."""
    url = "https://api.callmebot.com/whatsapp.php"
    params = {
        "phone": phone,
        "text": message,
        "apikey": api_key
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            print("  [OK] WhatsApp message sent via CallMeBot!")
            return True
        else:
            print(f"  [!] CallMeBot returned status {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"  [!] CallMeBot request failed: {e}")
        return False

def send_whatsapp_twilio(account_sid: str, auth_token: str, from_number: str, to_number: str, message: str) -> bool:
    """Send WhatsApp message using Twilio API."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {
        "From": f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number,
        "To": f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
        "Body": message
    }
    try:
        resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=30)
        if resp.status_code in (200, 201):
            print("  [OK] WhatsApp message sent via Twilio!")
            return True
        else:
            print(f"  [!] Twilio returned status {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"  [!] Twilio request failed: {e}")
        return False

def notify_top_jobs_whatsapp():
    config = load_config()
    wa_config = config.get("whatsapp", {})
    
    # Also check Environment variables (useful for GitHub Secrets)
    provider = os.getenv("WHATSAPP_PROVIDER") or wa_config.get("provider", "callmebot")
    phone = os.getenv("WHATSAPP_PHONE") or wa_config.get("phone", "+917872567781")
    api_key = os.getenv("CALLMEBOT_API_KEY") or wa_config.get("callmebot_api_key", "")
    
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID") or wa_config.get("twilio_account_sid", "")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN") or wa_config.get("twilio_auth_token", "")
    twilio_from = os.getenv("TWILIO_FROM_NUMBER") or wa_config.get("twilio_from_number", "")

    import re
    github_repo = os.getenv("GITHUB_REPOSITORY") or "SouravRay17/job-discovery-assistant"

    # Fetch top >=70% matches from DB
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url 
            FROM jobs 
            WHERE score >= 70 AND status != 'rejected'
            ORDER BY score DESC 
            LIMIT 10
        """)
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[*] No >=70% job matches found to send via WhatsApp.")
        return

    # Build formatted WhatsApp message
    msg_lines = [
        "🚀 *Job Discovery Assistant — Daily Top 10 Matches*",
        f"Here are your top *{len(rows)}* roles matching >70% with tailored resumes:\n"
    ]

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

    msg_lines.append("📄 Tailored LaTeX PDF Resumes compiled in your repo `exports/` folder!")
    message_text = "\n".join(msg_lines)

    print("\n" + "="*60)
    print("Sending WhatsApp Notification...")
    print("="*60)
    try:
        print(message_text)
    except UnicodeEncodeError:
        print(message_text.encode("utf-8", errors="ignore").decode("ascii", errors="ignore"))
    print("="*60)

    if provider == "callmebot":
        if not api_key:
            print("  [!] CALLMEBOT_API_KEY missing in config.yaml or Environment. Skipping send.")
            return
        send_whatsapp_callmebot(phone, api_key, message_text)
    elif provider == "twilio":
        if not twilio_sid or not twilio_token:
            print("  [!] Twilio credentials missing in config.yaml or Environment. Skipping send.")
            return
        send_whatsapp_twilio(twilio_sid, twilio_token, twilio_from, phone, message_text)

if __name__ == "__main__":
    notify_top_jobs_whatsapp()
