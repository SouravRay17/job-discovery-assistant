"""
tailor.py — Generate tailored application materials (resume summary & cover letter)
using LLM (Ollama local or Google Gemini cloud) without fabricating qualifications.
"""

import json
import os
import re
import sys
import requests

from db import get_connection
from scorer import validate_environment, parse_and_validate_json

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


def query_tailor_llm(prompt: str, config: dict) -> dict | None:
    """Send tailoring prompt to LLM (Ollama or Gemini) and return parsed JSON output."""
    from llm_client import query_llm

    response_text = query_llm(
        prompt=prompt,
        config=config,
        temperature=0.5,
        max_tokens=1500,
        json_mode=True
    )
    if not response_text:
        print("  [!] LLM returned empty response.")
        return None

    # Try strict JSON load first
    match = re.search(r"(\{.*\})", response_text, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str, strict=False)
            if "tailored_summary" in data and "cover_letter_draft" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Robust regex extraction fallback
    summary_match = re.search(r'"tailored_summary"\s*:\s*"(.*?)"\s*,\s*"cover_letter_draft"', response_text, re.DOTALL)
    if not summary_match:
        summary_match = re.search(r'"tailored_summary"\s*:\s*"(.*?)"(?=\s*,\s*"|(?:\s*,\s*\n?\s*\}))', response_text, re.DOTALL)

    cover_match = re.search(r'"cover_letter_draft"\s*:\s*"(.*?)"\s*\}', response_text, re.DOTALL)
    if not cover_match:
        cover_match = re.search(r'"cover_letter_draft"\s*:\s*"(.*?)"(?=\s*,\s*"|(?:\s*,\s*\n?\s*\}))', response_text, re.DOTALL)

    if summary_match and cover_match:
        summary = summary_match.group(1).strip().replace('\\n', '\n').replace('\\"', '"')
        cover = cover_match.group(1).strip().replace('\\n', '\n').replace('\\"', '"')
        return {"tailored_summary": summary, "cover_letter_draft": cover}

    print("  [!] Failed to parse tailored summary and cover letter from LLM response.")
    print(f"      Response was:\n{response_text[:300]}...")
    return None


def tailor_job(job_source: str, job_id: str, config: dict, cv_profile: dict) -> bool:
    """Generate and save tailored summary and cover letter for a specific job."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT title, company, location, remote, description_raw FROM jobs WHERE source = ? AND id = ?",
            (job_source, job_id)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        print(f"  [!] Job {job_source} / {job_id} not found in database.")
        return False

    title, company, location, remote, description = row
    if not description:
        print(f"  [*] Description empty for {job_source}/{job_id}. Attempting lazy fetch...")
        if job_source.startswith("greenhouse:"):
            board = job_source.split(":", 1)[1]
            from scraper import GreenhouseFetcher
            description = GreenhouseFetcher.fetch_description(board, job_id)
        elif job_source.startswith("workday:"):
            company_slug = job_source.split(":", 1)[1]
            from scraper import WorkdayFetcher
            description = WorkdayFetcher.fetch_description(company_slug, job_id)

        if description:
            # Save fetched description back to DB
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
        print("  [!] Job description is empty or unavailable. Cannot tailor.")
        return False

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

    # Save back to DB
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


def clean_date(date_str: str) -> str:
    """Standardise date format for RenderCV compatibility (YYYY-MM or YYYY or 'present')."""
    if not date_str:
        return ""
    date_clean = date_str.strip().lower()
    if date_clean in ("present", "now", "current"):
        return "present"
        
    if re.match(r'^\d{4}$', date_clean):
        return date_clean
        
    months_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        "january": "01", "february": "02", "march": "03", "april": "04", "june": "06",
        "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12"
    }
    
    m = re.search(r'([a-zA-Z]+)\s*(\d{4})', date_clean)
    if m:
        month_name = m.group(1)
        year = m.group(2)
        month_num = months_map.get(month_name, "01")
        return f"{year}-{month_num}"
        
    m_year = re.search(r'\b(\d{4})\b', date_clean)
    if m_year:
        return m_year.group(1)
        
    return date_str


def escape_latex(text: str) -> str:
    """Escape special LaTeX characters in a plain text string."""
    if not text:
        return ""
    # Escape standard special characters
    chars = {
        '&': r'\&',
        '%': r'\%',
        '_': r'\_',
        '$': r'\$',
        '#': r'\#',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    
    escaped = ""
    for char in text:
        escaped += chars.get(char, char)
        
    # Translate bold markdown to LaTeX bold
    escaped = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', escaped)
    return escaped


def compile_pdf_resume(job_source: str, job_id: str) -> str | None:
    """Generate a complete resume by injecting the tailored summary into the master LaTeX template
    and compiling it using tectonic.exe.
    Returns the path of the generated PDF.
    """
    import subprocess

    # Load environment
    config, cv_profile = validate_environment()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    master_tex_path = os.path.join(base_dir, "Sourav_Ray_Resume_Master.tex")
    # Resolve Tectonic compiler binary cross-platform
    import shutil
    tectonic_bin = shutil.which("tectonic")
    if not tectonic_bin:
        # Fallback to local tectonic.exe (Windows) or tectonic (Linux) in workspace
        local_exe = os.path.join(base_dir, "tectonic.exe")
        local_bin = os.path.join(base_dir, "tectonic")
        if os.path.exists(local_exe):
            tectonic_bin = local_exe
        elif os.path.exists(local_bin):
            tectonic_bin = local_bin

    exports_dir = os.path.join(base_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)

    if not tectonic_bin:
        print("  [!] Tectonic LaTeX compiler not found in PATH or workspace. Skipping PDF compilation.")
        return None

    # 1. Fetch tailored summary from DB
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT company, tailored_summary FROM jobs WHERE source = ? AND id = ?",
            (job_source, job_id)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row or not row[1]:
        print(f"  [!] Tailored summary not found in DB for {job_source}/{job_id}. Run tailoring first.")
        return None

    company, summary_text = row
    company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)
    temp_tex_name = f"temp_cv_{company_clean}_{job_id}.tex"
    temp_tex_path = os.path.join(exports_dir, temp_tex_name)
    temp_pdf_path = os.path.join(exports_dir, f"temp_cv_{company_clean}_{job_id}.pdf")
    output_pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}.pdf")

    # 2. Modify LaTeX Template
    try:
        with open(master_tex_path, "r", encoding="utf-8") as f:
            tex_content = f.read()
    except Exception as e:
        print(f"  [!] Failed to read master LaTeX template: {e}")
        return None

    escaped_summary = escape_latex(summary_text)
    summary_latex = f"\\section*{{Professional Summary}}\n\n{escaped_summary}\n\n"

    if "\\section*{Highlights}" in tex_content:
        tex_content = tex_content.replace("\\section*{Highlights}", summary_latex + "\\section*{Highlights}")
    else:
        # Fallback to insert right after \begin{document}
        print("  [!] '\\section*{Highlights}' not found in template. Prepending summary to document body.")
        tex_content = tex_content.replace("\\begin{document}", f"\\begin{{document}}\n\n{summary_latex}")

    try:
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
    except Exception as e:
        print(f"  [!] Failed to write temporary LaTeX file: {e}")
        return None

    # 3. Render using Tectonic CLI
    try:
        print(f"  * Compiling LaTeX resume via Tectonic...")
        cmd = [tectonic_bin, temp_tex_path, "--outdir", exports_dir]
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        subprocess.run(cmd, env=env, capture_output=True, encoding="utf-8", check=True)

        if os.path.exists(temp_pdf_path):
            if os.path.exists(output_pdf_path):
                os.remove(output_pdf_path)
            os.rename(temp_pdf_path, output_pdf_path)
        else:
            print("  [!] Tectonic compiled successfully but output PDF was not found.")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"  [!] Tectonic compilation failed. Checking error logs...")
        log_path = os.path.join(exports_dir, "tectonic_error.log")
        with open(log_path, "w", encoding="utf-8") as lf:
            lf.write(f"Command: {e.cmd}\n")
            lf.write(f"Exit code: {e.returncode}\n")
            lf.write(f"Stdout:\n{e.stdout or ''}\n")
            lf.write(f"Stderr:\n{e.stderr or ''}\n")
        print(f"      Full error log written to {log_path}")
        return None
    except Exception as e:
        print(f"  [!] Tectonic execution failed: {e}")
        return None
    finally:
        # Clean up temp TEX
        if os.path.exists(temp_tex_path):
            os.remove(temp_tex_path)

    print(f"  [OK] LaTeX Typeset PDF Resume created at: {output_pdf_path}")
    return output_pdf_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Tailor application materials for a job")
    parser.add_argument("--source", type=str, required=True, help="Job source (e.g. greenhouse:stripe)")
    parser.add_argument("--id", type=str, required=True, help="Job ID")
    args = parser.parse_args()

    config, cv_profile = validate_environment()

    success = tailor_job(args.source, args.id, config, cv_profile)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
