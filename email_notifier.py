"""
email_notifier.py — Send daily job digest and attached tailored PDF resumes via Gmail SMTP.

Reads Top 10 recommendations from candidate_job_scores and sends structured HTML digest.
"""

import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime, timezone

from config import load_config
from db import get_connection, init_db
import tailor


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_email_digest(top_n: int = 10):
    init_db()
    config = load_config()
    email_cfg = config.get("email", {})

    sender = os.getenv("SENDER_EMAIL") or email_cfg.get("sender_email", "sroy.dgp2014@gmail.com")
    recipient = os.getenv("RECIPIENT_EMAIL") or email_cfg.get("recipient_email", sender)
    password = os.getenv("GMAIL_APP_PASSWORD") or email_cfg.get("gmail_app_password", "")

    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT c.source, c.job_id, j.company, j.title, c.llm_score,
                   c.recommendation, c.match_reason, c.strengths, c.skill_gaps,
                   j.location, j.url, c.tailored_summary, c.hybrid_retrieval_score, c.reranker_score
            FROM candidate_job_scores c
            JOIN jobs j ON c.source = j.source AND c.job_id = j.id
            WHERE c.notified_email = 0 AND (c.recommendation IN ('APPLY', 'MAYBE') OR c.mmr_selected = 1)
            ORDER BY c.llm_score DESC, c.reranker_score DESC LIMIT ?
        """, (top_n,))
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not rows:
        print("[*] No new unnotified job recommendations found.")
        return

    print(f"\n{'='*60}\nPreparing Email Digest for {len(rows)} Top Roles -> {recipient}\n{'='*60}")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🚀 Top {len(rows)} AI & Data Roles Recommendation Digest"
    msg["From"] = f"Job Discovery Assistant <{sender}>"
    msg["To"] = recipient

    exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
    github_repo = os.getenv("GITHUB_REPOSITORY") or "SouravRay17/job-discovery-assistant"
    items_html = []

    for idx, item in enumerate(rows, 1):
        source = item["source"]
        job_id = item["job_id"]
        company = item["company"]
        title = item["title"]
        score = item["llm_score"] or int((item["reranker_score"] or 0.8) * 100)
        rec = item["recommendation"] or "APPLY"
        reason = item["match_reason"] or "Strong technical synergy in hybrid retrieval."
        strengths = json.loads(item["strengths"] or "[]")
        summary = item["tailored_summary"] or ""
        location = item["location"]
        url = item["url"]

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

        badge_color = "#22c55e" if rec == "APPLY" else "#eab308"
        strengths_html = "".join(f"<span style='background:#334155;color:#38bdf8;padding:2px 6px;margin-right:4px;border-radius:3px;font-size:11px;'>{s}</span>" for s in strengths[:4])

        items_html.append(f"""
        <div style="border-left:4px solid #38bdf8;background:#1e293b;color:#f8fafc;padding:14px;margin:14px 0;border-radius:6px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <h3 style="margin:0;color:#38bdf8;font-size:16px;">{idx}. {title} — <span style="color:#4ade80;">{score}/100</span></h3>
                <span style="background:{badge_color};color:#000;font-weight:bold;padding:2px 8px;border-radius:4px;font-size:12px;">{rec}</span>
            </div>
            <p style="margin:4px 0;color:#94a3b8;font-size:13px;">🏢 <strong>{company}</strong> &nbsp;|&nbsp; 📍 {location}</p>
            <p style="margin:6px 0;font-size:13px;color:#cbd5e1;"><strong>Why Apply:</strong> {reason}</p>
            <div style="margin:6px 0;">{strengths_html}</div>
            {f'<p style="margin:6px 0;font-size:12px;color:#94a3b8;border-top:1px solid #334155;padding-top:6px;"><em>Summary: "{summary[:150]}..."</em></p>' if summary else ''}
            <p style="margin:8px 0 0 0;">
                <a href="{url}" style="color:#60a5fa;text-decoration:none;font-weight:bold;">🔗 Apply Now</a> &nbsp;|&nbsp; 
                <a href="{github_url}" style="color:#94a3b8;text-decoration:none;">📄 View LaTeX PDF</a>
            </p>
        </div>
        """)

    body = f"""
    <div style="font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:20px;max-width:640px;margin:auto;border-radius:8px;">
        <h2 style="color:#38bdf8;margin-top:0;">🚀 Job Discovery Assistant — Top Recommendations</h2>
        <p style="color:#cbd5e1;font-size:14px;">Here are your top {len(rows)} curated opportunities evaluated via Retrieval-First Architecture (Vector + BM25 + Cross-Encoder + Gemini Review). Tailored resumes are attached.</p>
        {"".join(items_html)}
        <p style="color:#64748b;font-size:11px;margin-top:20px;">Delivered by Job Discovery Assistant • Retrieval-First Engine</p>
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
            now_str = now_iso()
            for item in rows:
                conn.execute(
                    "UPDATE candidate_job_scores SET notified_email = 1, notified_at = ? WHERE source = ? AND job_id = ?",
                    (now_str, item["source"], item["job_id"])
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [ERR] Failed to send email: {e}")


if __name__ == "__main__":
    send_email_digest(top_n=10)
