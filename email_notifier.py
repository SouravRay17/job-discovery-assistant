"""
email_notifier.py — Send daily job digest and attached tailored PDF resumes via Gmail SMTP.

Sent from candidate's email (sroy.dgp2014@gmail.com) directly to themselves.

Features:
  - Responsive, modern HTML email formatting
  - Job Role, Company Name, Match Score, Location, and Direct Apply Link
  - Automatically attaches top matching tailored PDF resumes from exports/
"""

import os
import re
import smtplib
import sqlite3
import sys
import yaml
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from db import get_connection
import tailor

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

def send_email_digest(top_n: int = 10):
    config = load_config()
    email_cfg = config.get("email", {})
    
    sender_email = os.getenv("SENDER_EMAIL") or email_cfg.get("sender_email", "sroy.dgp2014@gmail.com")
    recipient_email = os.getenv("RECIPIENT_EMAIL") or email_cfg.get("recipient_email", sender_email)
    app_password = os.getenv("GMAIL_APP_PASSWORD") or email_cfg.get("gmail_app_password", "")
    smtp_server = email_cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = email_cfg.get("smtp_port", 587)

    threshold = config.get("scoring", {}).get("threshold", 70)

    # 1. Fetch top >=70% matches from DB
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url, tailored_summary
            FROM jobs
            WHERE score >= ? 
              AND status != 'rejected'
              AND description_raw IS NOT NULL 
              AND LENGTH(TRIM(description_raw)) > 0
            ORDER BY score DESC
            LIMIT ?
        """, (threshold, top_n))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[*] No >=70% job matches found to send via Email.")
        return

    print(f"\n{'='*60}")
    print(f"Preparing Email Digest for {len(rows)} Top Roles -> {recipient_email}")
    print(f"{'='*60}")

    # Build MIMEMultipart email
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🚀 Daily Job Discovery Digest: {len(rows)} Top Matches (>70%) & Tailored Resumes"
    msg["From"] = f"Job Discovery Assistant <{sender_email}>"
    msg["To"] = recipient_email

    # HTML Body Construction
    html_items = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")
    github_repo = os.getenv("GITHUB_REPOSITORY") or "SouravRay17/job-discovery-assistant"

    attached_files = 0

    for idx, (source, job_id, company, title, score, location, url, summary) in enumerate(rows, 1):
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
        pdf_name = f"Sourav_Resume_{company_clean}_{job_id}.pdf"
        pdf_path = os.path.join(exports_dir, pdf_name)
        github_pdf_url = f"https://github.com/{github_repo}/blob/main/exports/{pdf_name}"

        # Ensure PDF resume is compiled
        if not os.path.exists(pdf_path):
            pdf_path = tailor.compile_pdf_resume(source, job_id) or pdf_path

        # Attach PDF file to email if it exists
        if pdf_path and os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                    msg.attach(part)
                    attached_files += 1
            except Exception as e:
                print(f"  [!] Failed to attach {pdf_name}: {e}")

        # Item HTML
        html_items.append(f"""
        <div style="background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0; color: #38bdf8; font-size: 18px;">{idx}. {title}</h3>
                <span style="background-color: #16a34a; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 14px;">Match: {score}/100</span>
            </div>
            <p style="margin: 6px 0; font-size: 15px; color: #94a3b8;">🏢 <strong>{company}</strong> &nbsp;|&nbsp; 📍 {location}</p>
            {f'<p style="margin: 8px 0; font-size: 14px; color: #cbd5e1; font-style: italic;">"{summary[:200]}..."</p>' if summary else ''}
            <div style="margin-top: 12px;">
                <a href="{url}" style="background-color: #2563eb; color: white; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; margin-right: 10px;" target="_blank">🔗 Apply Now</a>
                <a href="{github_pdf_url}" style="background-color: #475569; color: white; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;" target="_blank">📄 View PDF on GitHub</a>
            </div>
        </div>
        """)

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px;">
        <div style="max-width: 680px; margin: 0 auto; background-color: #0f172a;">
            <h2 style="color: #38bdf8; border-bottom: 2px solid #334155; padding-bottom: 10px;">
                🚀 Job Discovery Assistant — Daily Top Matches & Tailored Resumes
            </h2>
            <p style="font-size: 15px; color: #cbd5e1;">
                Hi Sourav, here are your top <strong>{len(rows)}</strong> job openings matching <strong>>70%</strong> for your candidate profile.
                Tailored PDF resumes have been generated and attached below!
            </p>
            {"".join(html_items)}
            <p style="font-size: 13px; color: #64748b; margin-top: 20px; text-align: center;">
                Generated automatically by your local Job Discovery Assistant pipeline.
            </p>
        </div>
    </body>
    </html>
    """

    # Attach HTML body
    msg.attach(MIMEText(full_html, "html"))

    # Send via SMTP
    if not app_password:
        print("  [!] GMAIL_APP_PASSWORD missing in config.yaml or Environment. Skipping email dispatch.")
        print("  [*] Printed HTML preview above. To enable automatic sending, add gmail_app_password to config.yaml!")
        return

    try:
        print(f"  * Connecting to {smtp_server}:{smtp_port}...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)
        server.quit()
        print(f"  [OK] Email successfully sent to {recipient_email} with {attached_files} attached PDF resumes!")
    except Exception as e:
        print(f"  [ERR] Failed to send email: {e}")

if __name__ == "__main__":
    send_email_digest(top_n=10)
