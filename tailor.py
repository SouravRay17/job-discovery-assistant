"""
tailor.py — Generate tailored application materials (resume summary & cover letter)
using LLM (Ollama local or Google Gemini cloud) without fabricating qualifications.

Usage:
    python tailor.py --source greenhouse:stripe --id 12345
    python tailor.py --batch [--top 10]
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

from config import load_config
from db import get_connection
from scorer import validate_environment

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


def clean_date(date_str: str) -> str:
    """Standardise date format (YYYY-MM, YYYY, or 'present') using stdlib datetime."""
    if not date_str:
        return ""
    date_clean = date_str.strip().lower()
    if date_clean in ("present", "now", "current"):
        return "present"

    for fmt in ("%B %Y", "%b %Y", "%Y-%m", "%Y/%m", "%Y"):
        try:
            dt = datetime.strptime(date_clean, fmt)
            return dt.strftime("%Y-%m") if any(k in fmt for k in ("%m", "%b", "%B")) else dt.strftime("%Y")
        except ValueError:
            pass

    return date_str


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters using native str.translate."""
    if not text:
        return ""
    escaped = text.translate(LATEX_TRANS)
    return re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', escaped)


def query_tailor_llm(prompt: str, config: dict) -> dict | None:
    """Send tailoring prompt to LLM (Ollama or Gemini) and return parsed JSON output."""
    from llm_client import query_llm

    response_text = query_llm(prompt=prompt, config=config, temperature=0.5, max_tokens=1500, json_mode=True)
    if not response_text:
        return None

    match = re.search(r"(\{.*\})", response_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1), strict=False)
            if "tailored_summary" in data and "cover_letter_draft" in data:
                return data
        except json.JSONDecodeError:
            pass

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
            "SELECT title, company, location, remote, description_raw FROM jobs WHERE source = ? AND id = ?",
            (job_source, job_id)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        print(f"  [!] Job {job_source} / {job_id} not found in database.")
        return False

    title, company, location, remote, description = row
    if not description:
        from scraper import fetch_greenhouse_description, fetch_workday_description
        if job_source.startswith("greenhouse:"):
            description = fetch_greenhouse_description(job_source.split(":", 1)[1], job_id)
        elif job_source.startswith("workday:"):
            description = fetch_workday_description(job_source.split(":", 1)[1], job_id)

        if description:
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE jobs SET description_raw = ? WHERE source = ? AND id = ?",
                    (description, job_source, job_id)
                )
                conn.commit()
            finally:
                conn.close()

    if not description:
        description = f"Role: {title} at {company} located in {location}. Remote preference: {remote}."

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

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND id = ?",
            (result["tailored_summary"], result["cover_letter_draft"], job_source, job_id)
        )
        conn.commit()
    finally:
        conn.close()

    print("  [OK] Tailored summary and cover letter saved successfully.")
    return True


def compile_pdf_resume(job_source: str, job_id: str) -> str | None:
    """Generate a complete resume by injecting tailored summary into LaTeX and compiling via Tectonic."""
    config, _ = validate_environment()
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
            "SELECT company, tailored_summary FROM jobs WHERE source = ? AND id = ?",
            (job_source, job_id)
        ).fetchone()
    finally:
        conn.close()

    if not row or not row[1]:
        return None

    company, summary_text = row
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
    if "\\section*{Highlights}" in tex_content:
        tex_content = tex_content.replace("\\section*{Highlights}", summary_latex + "\\section*{Highlights}")
    else:
        tex_content = tex_content.replace("\\begin{document}", f"\\begin{{document}}\n\n{summary_latex}")

    try:
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        subprocess.run([tectonic_bin, temp_tex_path, "--outdir", exports_dir], capture_output=True, check=True)

        if os.path.exists(temp_pdf_path):
            if os.path.exists(output_pdf_path):
                os.remove(output_pdf_path)
            os.rename(temp_pdf_path, output_pdf_path)
        else:
            return None
    except Exception as e:
        print(f"  [!] Tectonic compilation error: {e}")
        return None
    finally:
        if os.path.exists(temp_tex_path):
            os.remove(temp_tex_path)

    print(f"  [OK] LaTeX Typeset PDF Resume created: {output_pdf_path}")
    return output_pdf_path


def run_batch_tailoring(top_n: int | None = 10):
    """Batch generate tailored summaries, cover letters, and PDFs for qualifying jobs."""
    config = load_config()
    threshold = config.get("scoring", {}).get("threshold", 60)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exports_dir = os.path.join(base_dir, "exports")

    if os.path.exists(exports_dir):
        for old_file in glob.glob(os.path.join(exports_dir, "*")):
            try:
                if os.path.isfile(old_file):
                    os.remove(old_file)
            except Exception:
                pass
    else:
        os.makedirs(exports_dir, exist_ok=True)

    conn = get_connection()
    try:
        query = """
            SELECT source, id, company, title, score, location, remote, url, tailored_summary
            FROM jobs WHERE score >= ? AND status = 'to_review' AND description_raw IS NOT NULL
            ORDER BY score DESC
        """
        params = [threshold]
        if top_n:
            query += " LIMIT ?"
            params.append(top_n)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"[*] No jobs found with score >= {threshold}.")
        return

    print(f"\n{'='*60}\nBatch Tailoring -- Processing {len(rows)} Openings\n{'='*60}")
    tailored_count, pdf_count = 0, 0

    for idx, (source, job_id, company, title, score, location, remote, url, existing_summary) in enumerate(rows, 1):
        print(f"\n[{idx}/{len(rows)}] [{score}/100] {company} — {title} ({location})")
        if not existing_summary:
            cfg, cv_profile = validate_environment()
            if tailor_job(source, job_id, cfg, cv_profile):
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
        config, cv_profile = validate_environment()
        if not tailor_job(args.source, args.id, config, cv_profile):
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
