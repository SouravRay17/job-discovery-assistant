"""
tailor.py — Generate tailored application materials (resume summary & cover letter)
using LLM (Ollama local or Google Gemini cloud) without fabricating qualifications.

Targeting:
    Evaluates only the final Top 10 recommendations from candidate_job_scores.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from config import load_config, CV_PATH
from db import get_connection, init_db
from retriever import load_candidate_profile

SYSTEM_PROMPT = """You are an expert executive resume strategist and ATS optimization expert.
You will be given a candidate profile and a target job description.

Your objective is to draft a high-converting, ATS-optimized Professional Summary and Cover Letter tailored specifically to maximize interview callback rates for this role.

GUIDELINES FOR HIGH CONVERSION (MAXIMUM INTERVIEW PROBABILITY):
1. **ATS Keyword Alignment**: Identify key technical skills, tools, frameworks, and domain terms from the job description (e.g., Python, PySpark, SQL, Airflow, Snowflake, AWS, Data Engineering, LLMs, MLOps, APIs). Seamlessly integrate matching terms from the candidate's profile into the summary.
2. **Impact & Seniority Alignment**: Position candidate Sourav Ray as a Data & AI Engineer with 3+ years of experience and an M.Tech degree, emphasizing production data engineering, pipeline reliability, and AI/ML capabilities.
3. **Concise & Punchy**: Keep the summary to 3-4 powerful, impactful sentences.

HARD CONSTRAINTS:
- Do NOT fabricate or embellish any qualifications, employers, dates, projects, or skills not present in the candidate profile.
- Every claim MUST be grounded in the candidate profile.
- Return ONLY valid JSON in this exact format, no other text:
{
  "tailored_summary": "<3-4 sentence high-impact, ATS-optimized professional summary>",
  "cover_letter_draft": "<3-paragraph compelling cover letter connecting candidate experience to the job requirements>"
}"""

LATEX_TRANS = str.maketrans({
    '&': r'\&', '%': r'\%', '_': r'\_', '$': r'\$', '#': r'\#',
    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
})


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_date(date_str: str) -> str:
    """Standardise date format using native datetime.fromisoformat or simple prefix slice."""
    if not date_str or date_str.lower().strip() in ("present", "now", "current"):
        return "present"
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%Y-%m")
    except ValueError:
        return date_str[:7] if len(date_str) >= 7 and date_str[:4].isdigit() else date_str


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters using native str.translate."""
    if not text:
        return ""
    escaped = text.translate(LATEX_TRANS)
    return re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', escaped)


def query_tailor_llm(prompt: str, config: dict) -> dict | None:
    """Send tailoring prompt to LLM and return parsed JSON output."""
    from llm_client import query_llm, parse_json_from_llm

    response_text = query_llm(prompt=prompt, config=config, temperature=0.5, max_tokens=1500, json_mode=True)
    if not response_text:
        return None

    data = parse_json_from_llm(response_text)
    if data and "tailored_summary" in data and "cover_letter_draft" in data:
        return data

    summary_match = re.search(r'"tailored_summary"\s*:\s*"(.*?)"(?=\s*,\s*"cover_letter_draft"|\s*,\s*"|\s*})', response_text, re.DOTALL)
    cover_match = re.search(r'"cover_letter_draft"\s*:\s*"(.*?)"(?=\s*})', response_text, re.DOTALL)

    if summary_match and cover_match:
        return {
            "tailored_summary": summary_match.group(1).strip().replace('\\n', '\n').replace('\\"', '"'),
            "cover_letter_draft": cover_match.group(1).strip().replace('\\n', '\n').replace('\\"', '"'),
        }

    return None


def tailor_job(job_source: str, job_id: str, config: dict, cv_profile: dict) -> bool:
    """Generate and save tailored summary and cover letter for a specific job."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT title, company, location, remote, description_raw, search_text FROM jobs WHERE source = ? AND id = ?",
            (job_source, job_id)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        print(f"  [!] Job {job_source} / {job_id} not found in database.")
        return False

    title, company, location, remote, description, search_text = row
    if not description:
        from scraper import fetch_greenhouse_description, fetch_workday_description
        if job_source.startswith("greenhouse:"):
            description = fetch_greenhouse_description(job_source.split(":", 1)[1], job_id)
        elif job_source.startswith("workday:"):
            description = fetch_workday_description(job_source.split(":", 1)[1], job_id)

    if not description:
        description = search_text or f"Role: {title} at {company} located in {location}."

    print(f"  * Tailoring for: {title} at {company}...")
    prompt = f"""{SYSTEM_PROMPT}

Candidate Profile:
{json.dumps(cv_profile, indent=2)}

Job Details:
Title: {title}
Company: {company}
Location: {location}
Remote: {remote}
Description:
{description}
"""

    result = query_tailor_llm(prompt, config)
    if not result:
        return False

    now_str = now_iso()
    conn = get_connection()
    try:
        # Update candidate_job_scores
        conn.execute(
            """UPDATE candidate_job_scores
               SET tailored_summary = ?, cover_letter_draft = ?, status = 'tailored', tailored_at = ?
               WHERE source = ? AND job_id = ?""",
            (result["tailored_summary"], result["cover_letter_draft"], now_str, job_source, job_id)
        )
        conn.commit()
    finally:
        conn.close()

    print("  [OK] Tailored summary and cover letter saved successfully.")
    return True


def compile_pdf_resume(job_source: str, job_id: str) -> str | None:
    """Generate a complete resume by injecting tailored summary into LaTeX and compiling via Tectonic."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    master_tex_path = os.path.join(base_dir, "Sourav_Ray_Resume_Master.tex")

    tectonic_bin = shutil.which("tectonic") or next(
        (os.path.join(base_dir, b) for b in ("tectonic.exe", "tectonic") if os.path.exists(os.path.join(base_dir, b))),
        None
    )

    exports_dir = os.path.join(base_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)

    if not tectonic_bin:
        print("  [!] Tectonic LaTeX compiler not found. Skipping PDF compilation.")
        return None

    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT j.company, c.tailored_summary, j.title
               FROM jobs j
               LEFT JOIN candidate_job_scores c ON c.source = j.source AND c.job_id = j.id
               WHERE j.source = ? AND j.id = ?""",
            (job_source, job_id)
        ).fetchone()
    finally:
        conn.close()

    company = row[0] if row and row[0] else "Company"
    summary_text = row[1] if row and row[1] else None
    title = row[2] if row and len(row) > 2 and row[2] else "Data & AI Engineer"

    # Default fallback summary if LLM tailoring hasn't run yet
    if not summary_text:
        summary_text = (
            f"Results-driven Data & AI Engineer with 3+ years of enterprise experience building production "
            f"data platforms, high-throughput ETL/ELT pipelines, and Generative AI systems. Proven expertise in "
            f"Snowflake, AWS, PySpark, dbt, Apache Airflow, and Multi-Agent Orchestration (MCP). Targeting the {title} role at {company}."
        )

    company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
    temp_tex_path = os.path.join(exports_dir, f"temp_cv_{company_clean}_{job_id}.tex")
    temp_pdf_path = os.path.join(exports_dir, f"temp_cv_{company_clean}_{job_id}.pdf")
    output_pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}.pdf")

    try:
        with open(master_tex_path, "r", encoding="utf-8") as f:
            tex_content = f.read()
    except Exception as e:
        print(f"  [!] Failed to read master LaTeX template: {e}")
        return None

    summary_latex = f"\\section*{{Professional Summary}}\n\n{escape_latex(summary_text)}\n\n"
    if "\\section*{Technical Skills}" in tex_content:
        tex_content = tex_content.replace("\\section*{Technical Skills}", summary_latex + "\\section*{Technical Skills}")
    elif "\\section*{Highlights}" in tex_content:
        tex_content = tex_content.replace("\\section*{Highlights}", summary_latex + "\\section*{Highlights}")
    else:
        tex_content = tex_content.replace("\\begin{document}", f"\\begin{{document}}\n\n{summary_latex}")

    try:
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        result = subprocess.run([tectonic_bin, temp_tex_path, "--outdir", exports_dir], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [!] Tectonic compilation returned {result.returncode}: {result.stderr or result.stdout}")

        if os.path.exists(temp_pdf_path):
            if os.path.exists(output_pdf_path):
                os.remove(output_pdf_path)
            os.rename(temp_pdf_path, output_pdf_path)
        elif not os.path.exists(output_pdf_path):
            return None
    except Exception as e:
        print(f"  [!] Tectonic execution error: {e}")
        return None
    finally:
        if os.path.exists(temp_tex_path):
            try:
                os.remove(temp_tex_path)
            except Exception:
                pass

    print(f"  [OK] LaTeX Typeset PDF Resume created: {output_pdf_path} ({os.path.getsize(output_pdf_path)} bytes)")
    return output_pdf_path


def run_batch_tailoring(top_n: int = 10):
    """Batch generate tailored summaries, cover letters, and PDFs for top recommendations."""
    init_db()
    config = load_config()
    cv_profile = load_candidate_profile()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")

    os.makedirs(exports_dir, exist_ok=True)

    conn = get_connection()
    try:
        cursor = conn.execute(
            """SELECT c.source, c.job_id, j.company, j.title, c.llm_score,
                      j.location, j.remote, j.url, c.tailored_summary, c.recommendation
               FROM candidate_job_scores c
               JOIN jobs j ON c.source = j.source AND c.job_id = j.id
               WHERE c.recommendation IN ('APPLY', 'MAYBE') OR c.mmr_selected = 1
               ORDER BY c.llm_score DESC, c.reranker_score DESC
               LIMIT ?""",
            (top_n,)
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not rows:
        print("[*] No qualifying candidates found for batch tailoring. Run scorer.py first.")
        return

    print(f"\n{'='*60}\nBatch Tailoring & Resume Generation -- Processing {len(rows)} Openings\n{'='*60}")
    tailored_count, pdf_count = 0, 0

    for idx, item in enumerate(rows, 1):
        source = item["source"]
        job_id = item["job_id"]
        company = item["company"]
        title = item["title"]
        score = item["llm_score"] or "Pending"
        location = item["location"]
        rec = item["recommendation"] or "APPLY"
        existing_summary = item["tailored_summary"]

        print(f"\n[{idx}/{len(rows)}] [{rec} - {score}/100] {company} — {title} ({location})")
        if not existing_summary:
            if tailor_job(source, job_id, config, cv_profile):
                tailored_count += 1
            else:
                continue

        if compile_pdf_resume(source, job_id):
            pdf_count += 1

    print(f"\n{'='*60}\nBatch Tailoring Complete! Processed: {len(rows)} | Summaries: {tailored_count} | PDFs: {pdf_count}\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Tailor application materials for jobs")
    parser.add_argument("--source", type=str, help="Job source (e.g. greenhouse:stripe)")
    parser.add_argument("--id", type=str, help="Job ID")
    parser.add_argument("--batch", action="store_true", help="Run batch tailoring for top qualifying jobs")
    parser.add_argument("--top", type=int, default=10, help="Max jobs to process in batch mode")
    args = parser.parse_args()

    if args.batch:
        run_batch_tailoring(top_n=args.top)
    elif args.source and args.id:
        config = load_config()
        cv_profile = load_candidate_profile()
        if not tailor_job(args.source, args.id, config, cv_profile):
            sys.exit(1)
        compile_pdf_resume(args.source, args.id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
