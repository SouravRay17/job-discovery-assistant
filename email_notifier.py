"""
email_notifier.py — Send daily job digest and attached tailored PDF resumes via Gmail SMTP.

Usage:
    python email_notifier.py
"""

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from config import load_config
from db import get_connection
import tailor


def send_email_digest(top_n: int = 10):
    config = load_config()
    email_cfg = config.get("email", {})

    sender = os.getenv("SENDER_EMAIL") or email_cfg.get("sender_email", "sroy.dgp2014@gmail.com")
    recipient = os.getenv("RECIPIENT_EMAIL") or email_cfg.get("recipient_email", sender)
    password = os.getenv("GMAIL_APP_PASSWORD") or email_cfg.get("gmail_app_password", "")
    threshold = config.get("scoring", {}).get("threshold", 70)

    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url, tailored_summary
            FROM jobs
            WHERE score >= ? AND status = 'to_review' AND notified_email = 0 AND description_raw IS NOT NULL
            ORDER BY score DESC LIMIT ?
        """, (threshold, top_n))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        print("[*] No new unnotified >=70% job matches found.")
        return

    print(f"\n{'='*60}\nPreparing Email Digest for {len(rows)} Top Roles -> {recipient}\n{'='*60}")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🚀 Job Discovery Digest: {len(rows)} Top Matches (>70%)"
    msg["From"] = f"Job Discovery Assistant <{sender}>"
    msg["To"] = recipient

    exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
    github_repo = os.getenv("GITHUB_REPOSITORY") or "SouravRay17/job-discovery-assistant"
    items_html = []

    for idx, (source, job_id, company, title, score, location, url, summary) in enumerate(rows, 1):
        clean_co = re.sub(r'[^a-zA-Z0-9]', '_', company)
        pdf_name = f"Sourav_Resume_{clean_co}_{job_id}.pdf"
        pdf_path = os.path.join(exports_dir, pdf_name)
        github_url = f"https://github.com/{github_repo}/blob/main/exports/{pdf_name}"

        if not os.path.exists(pdf_path):
            pdf_path = tailor.compile_pdf_resume(source, job_id) or pdf_path

        if pdf_path and os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=pdf_name)
                    part['Content-Disposition'] = f'attachment; filename="{pdf_name}"'
                    msg.attach(part)
            except Exception:
                pass

        items_html.append(f"""
        <div style="border-left:4px solid #38bdf8;background:#1e293b;color:#f8fafc;padding:12px;margin:12px 0;border-radius:4px;">
            <h3 style="margin:0;color:#38bdf8;">{idx}. {title} — <span style="color:#4ade80;">{score}/100</span></h3>
            <p style="margin:4px 0;color:#94a3b8;">🏢 <strong>{company}</strong> &nbsp;|&nbsp; 📍 {location}</p>
            {f'<p style="margin:6px 0;font-size:13px;color:#cbd5e1;"><em>"{summary[:180]}..."</em></p>' if summary else ''}
            <p style="margin:6px 0;">
                <a href="{url}" style="color:#60a5fa;text-decoration:none;font-weight:bold;">🔗 Apply Now</a> &nbsp;|&nbsp; 
                <a href="{github_url}" style="color:#94a3b8;text-decoration:none;">📄 GitHub PDF</a>
            </p>
        </div>
        """)

    body = f"""
    <div style="font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:20px;max-width:640px;margin:auto;">
        <h2 style="color:#38bdf8;margin-top:0;">🚀 Job Discovery Digest</h2>
        <p style="color:#cbd5e1;">Here are your top {len(rows)} matching job openings (>70%). Tailored PDFs are attached.</p>
        {"".join(items_html)}
    </div>
    """
    msg.attach(MIMEText(body, "html"))

    if not password:
        print("  [!] GMAIL_APP_PASSWORD not set. Skipping email dispatch.")
        return

    try:
        server = smtplib.SMTP(email_cfg.get("smtp_server", "smtp.gmail.com"), email_cfg.get("smtp_port", 587))
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print(f"  [OK] Email successfully sent to {recipient}!")

        conn = get_connection()
        try:
            for (src, jid, _, _, _, _, _, _) in rows:
                conn.execute("UPDATE jobs SET notified_email = 1 WHERE source = ? AND id = ?", (src, jid))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [ERR] Failed to send email: {e}")


if __name__ == "__main__":
    send_email_digest(top_n=10)
