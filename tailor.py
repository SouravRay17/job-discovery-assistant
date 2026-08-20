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


def render_latex_from_profile(cv_profile: dict, summary_text: str, master_tex_path: str) -> str | None:
    """Dynamically populate the blank LaTeX master template exclusively from YAML candidate profile."""
    try:
        with open(master_tex_path, "r", encoding="utf-8") as f:
            tex = f.read()
    except Exception as e:
        print(f"  [!] Failed reading master template {master_tex_path}: {e}")
        return None

    p_info = cv_profile.get("personal_info", {})
    name = p_info.get("name", "Sourav Ray")
    loc = p_info.get("location", "Bengaluru, India")
    phone = p_info.get("phone", "+91-7872567781")
    email = p_info.get("email", "sroy.dgp2014@gmail.com")
    linkedin = p_info.get("linkedin", "linkedin.com/in/souravray17")
    github = p_info.get("github", "github.com/SouravRay17")

    linkedin_url = linkedin if linkedin.startswith("http") else f"https://{linkedin}"
    github_url = github if github.startswith("http") else f"https://{github}"

    tex = tex.replace("__CANDIDATE_NAME__", escape_latex(name))
    tex = tex.replace("__CANDIDATE_LOCATION__", escape_latex(loc))
    tex = tex.replace("__CANDIDATE_PHONE__", escape_latex(phone))
    tex = tex.replace("__CANDIDATE_EMAIL__", escape_latex(email))
    tex = tex.replace("__CANDIDATE_LINKEDIN_URL__", linkedin_url)
    tex = tex.replace("__CANDIDATE_LINKEDIN__", escape_latex(linkedin))
    tex = tex.replace("__CANDIDATE_GITHUB_URL__", github_url)
    tex = tex.replace("__CANDIDATE_GITHUB__", escape_latex(github))

    # Summary
    summary_latex = f"\\section*{{Professional Summary}}\n\n{escape_latex(summary_text)}\n"
    tex = tex.replace("__SECTION_SUMMARY__", summary_latex)

    # Technical Skills
    skills_latex = (
        r"\textbf{Cloud \& Data Platforms:} AWS (S3, Lambda, Kinesis, Firehose, DMS, CloudWatch), "
        r"Snowflake (Snowpark, Snowpipe, Cortex, Zero-Copy Cloning, Time Travel, Cost Optimization), GCP (Vertex AI, BigQuery)." "\n\n"
        r"\textbf{Data Engineering:} DBT, Apache Airflow, Apache Spark / PySpark, Coalesce, Apache Kafka, Apache Iceberg, SQL, "
        r"ETL/ELT, Data Contracts, Data Mesh, Bronze/Silver/Gold Architecture." "\n\n"
        r"\textbf{AI / ML \& GenAI:} Large Language Models (LLMs), Agentic AI, Multi-Agent Orchestration, Retrieval-Augmented "
        r"Generation (RAG), ChromaDB, Vector Search, Model Context Protocol (MCP), LangChain, LangGraph, TensorFlow, NLP, Prompt Engineering." "\n\n"
        r"\textbf{Programming \& Frameworks:} Python, SQL, Shell Scripting, FastAPI, Docker, Kubernetes, Git, GitHub Actions, CI/CD." "\n\n"
        r"\textbf{BI \& Tools:} Sigma, SAP BusinessObjects validation, Terraform, Linux."
    )
    tex = tex.replace("__SECTION_SKILLS__", skills_latex)

    # Projects & Experience
    projects_map = {p.get("id"): p for p in cv_profile.get("projects", [])}
    c360 = projects_map.get("customer_360_data_mesh", {})
    incident_ai = projects_map.get("ai_network_incident_orchestrator", {})
    schema_val = projects_map.get("genai_schema_validator", {})

    c360_bullets = "\n".join([f"\\item {escape_latex(b)}" for b in (c360.get("bullets", [])[:7] or [
        "Architected a petabyte-scale Customer 360 platform and Data Contract framework across 1,000+ sources, improving data accessibility by 60%.",
        "Engineered metadata-driven automation generating Silver and Gold DBT artifacts (.sql, .yml, .md), reducing pipeline development effort by 80%.",
        "Designed near real-time ingestion pipelines utilizing AWS DMS, Kinesis, Firehose, S3, and Snowpipe to onboard 1,000+ data sources into Snowflake.",
        "Built multi-stage data reconciliation engines utilizing row-count, column-count, and MD5-based hash verification to guarantee data fidelity.",
        "Implemented automated root cause analysis (RCA) tooling that detects column-level discrepancies, null-rate deviations, and schema drift.",
        "Validated legacy SAP BusinessObjects reporting logic against modernized Snowflake dimensional models, maintaining 100% metric consistency.",
        "Governed high-impact financial datasets (GL, revenue, transaction domains) with audit-ready automated compliance controls."
    ])])

    incident_bullets = "\n".join([f"\\item {escape_latex(b)}" for b in (incident_ai.get("bullets", [])[:4] or [
        "Engineered a multi-agent orchestrator coordinating specialized AI agents to accelerate network incident investigation and root cause analysis across ServiceNow, Infoblox, NetBox, SevOne, Datadog, Splunk, and LogicMonitor.",
        "Developed per-platform Model Context Protocol (MCP) servers providing a unified abstraction layer over observability APIs and secure SSH device sessions.",
        "Implemented dynamic agent selection and parallel correlation logic that merges alerts, topology, metrics, and logs into actionable RCA reports, cutting MTTD by 60% and MTTR by 65%.",
        "Enforced in-memory caching and concurrency controls (capped at 3 concurrent workers) to ensure high throughput under peak incident volume."
    ])])

    schema_bullets = "\n".join([f"\\item {escape_latex(b)}" for b in (schema_val.get("bullets", [])[:3] or [
        "Developed an enterprise-scale schema and report matching platform employing Python, Vector Search, and LLM inference across Exact, Semantic, and Heuristic match layers.",
        "Built governance safeguards to identify and mask PII attributes and leveraged LLMs to auto-generate metadata descriptions for undocumented legacy fields.",
        "Led UAT and validation across complex enterprise reporting models, eliminating manual mapping bottlenecks."
    ])])

    exp_latex = f"""\\textbf{{Factspan Analytics, Bengaluru, India}}

\\textit{{Senior Analyst / Data \\& AI Engineer}} \\hfill Sep 2023 -- Present

\\textbf{{Customer 360 Data Mesh \\& Governance (Petabyte-Scale) | AWS, Snowflake, DBT, Python}}
\\begin{{itemize}}
{c360_bullets}
\\end{{itemize}}

\\textbf{{AI-Powered Network Incident Orchestrator | Python, MCP, Multi-Agent, Observability}}
\\begin{{itemize}}
{incident_bullets}
\\end{{itemize}}

\\textbf{{GenAI Schema Validator \\& Automated Column Mapping | Python, Vector Search, LLMs}}
\\begin{{itemize}}
{schema_bullets}
\\end{{itemize}}"""
    tex = tex.replace("__SECTION_EXPERIENCE__", exp_latex)

    # Education
    edu_latex = (
        r"\textbf{National Institute of Technology (NIT) Durgapur} | M.Tech, Operations Research | CGPA: 8.36/10 \hfill 2021 -- 2023" "\n\n"
        r"\vspace{0.5mm}" "\n"
        r"\textbf{Government College of Engineering and Textile Technology (GCETTB)} | B.Tech \hfill 2015 -- 2019"
    )
    tex = tex.replace("__SECTION_EDUCATION__", edu_latex)

    # Certifications
    certs_latex = (
        r"\begin{itemize}" "\n"
        r"\item \textbf{Snowflake:} SnowPro Advanced Architect, SnowPro Advanced Data Scientist" "\n"
        r"\item \textbf{AWS Cloud:} AWS Certified Machine Learning -- Specialty, AWS Certified Solutions Architect -- Associate" "\n"
        r"\end{itemize}"
    )
    tex = tex.replace("__SECTION_CERTIFICATIONS__", certs_latex)

    return tex


def compile_pdf_resume(job_source: str, job_id: str) -> str | None:
    """Generate a complete resume by dynamically rendering YAML data into blank master LaTeX template and compiling via Tectonic."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    master_tex_path = os.path.join(base_dir, "Sourav_Ray_Resume_Master.tex")
    cv_profile = load_candidate_profile()

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

    tex_content = render_latex_from_profile(cv_profile, summary_text, master_tex_path)
    if not tex_content:
        return None

    try:
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        result = subprocess.run([tectonic_bin, temp_tex_path, "--outdir", exports_dir], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [!] Tectonic compilation returned {result.returncode}: {result.stderr or result.stdout}")

        if os.path.exists(temp_pdf_path):
            try:
                shutil.copy2(temp_pdf_path, output_pdf_path)
            except PermissionError:
                import time
                output_pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}_{int(time.time())}.pdf")
                shutil.copy2(temp_pdf_path, output_pdf_path)
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass
        elif not os.path.exists(output_pdf_path):
            return None
    except Exception as e:
        print(f"  [!] Tectonic execution error: {e}")
        return None
    finally:
        for p in (temp_tex_path, temp_pdf_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
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
               WHERE c.recommendation IN ('APPLY', 'MAYBE') OR c.mmr_selected = 1 OR c.hybrid_retrieval_score >= 0.4
               ORDER BY COALESCE(c.final_composite_score, c.llm_score/100.0, c.reranker_score, c.hybrid_retrieval_score) DESC
               LIMIT ?""",
            (top_n,)
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not rows:
        print("[*] No candidates retrieved yet. Running quick retrieval fallback...")
        from retriever import retrieve_jobs
        retrieve_jobs(top_k=20)
        conn = get_connection()
        try:
            cursor = conn.execute(
                """SELECT c.source, c.job_id, j.company, j.title, c.llm_score,
                          j.location, j.remote, j.url, c.tailored_summary, c.recommendation
                   FROM candidate_job_scores c
                   JOIN jobs j ON c.source = j.source AND c.job_id = j.id
                   ORDER BY c.hybrid_retrieval_score DESC LIMIT ?""",
                (top_n,)
            )
            rows = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    if not rows:
        print("[*] No jobs available in database to tailor.")
        return

    print(f"\n{'='*60}\nBatch Tailoring & Resume Generation -- Processing {len(rows)} Openings\n{'='*60}")
    tailored_count, pdf_count = 0, 0

    for idx, item in enumerate(rows, 1):
        source = item["source"]
        job_id = item["job_id"]
        company = item["company"]
        title = item["title"]
        score = item["llm_score"] or "Auto"
        location = item["location"]
        rec = item["recommendation"] or "APPLY"
        existing_summary = item["tailored_summary"]

        print(f"\n[{idx}/{len(rows)}] [{rec} - {score}] {company} — {title} ({location})")
        if not existing_summary:
            try:
                if tailor_job(source, job_id, config, cv_profile):
                    tailored_count += 1
            except Exception as e:
                print(f"  [!] Note: LLM tailoring skipped ({e}), compiling with verified candidate summary.")

        pdf_path = compile_pdf_resume(source, job_id)
        if pdf_path:
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
