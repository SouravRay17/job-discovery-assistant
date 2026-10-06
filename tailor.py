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
import jinja2
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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

latex_jinja_env = jinja2.Environment(
    block_start_string=r'\BLOCK{',
    block_end_string=r'}',
    variable_start_string=r'\VAR{',
    variable_end_string=r'}',
    comment_start_string=r'\#{',
    comment_end_string=r'}',
    line_statement_prefix='%%',
    line_comment_prefix='%#',
    trim_blocks=True,
    autoescape=False,
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR)
)


def select_target_headline(title: str, cv_profile: dict) -> str:
    """Select the most fitting target headline from candidate angles based on job title."""
    title_lower = (title or "").lower()
    if any(k in title_lower for k in ["data scientist", "predictive", "machine learning", "ml researcher", "research", "deep learning"]):
        return "Data Scientist | Predictive Modeling | Machine Learning | GenAI"
    elif any(k in title_lower for k in ["snowflake", "warehouse", "platform", "cloud data", "lakehouse"]):
        return "Data Engineer | Snowflake Platform Engineering | GenAI & Agentic AI Systems"
    elif any(k in title_lower for k in ["genai", "agent", "llm", "rag", "artificial intelligence"]):
        return "AI & GenAI Engineer | Agentic AI & RAG Systems | Data Platform Architecture"
    elif any(k in title_lower for k in ["software", "backend", "python developer"]):
        return "Software Engineer | AI & Data Engineer | ML Infrastructure | GenAI"
    elif any(k in title_lower for k in ["customer", "governance", "analytics"]):
        return "AI & Data Engineer | Technical Lead | GenAI | Customer Data & ML"
    return "Data Scientist | Predictive Modeling | Machine Learning | GenAI"


def build_resume_context(cv_profile: dict, job_title: str, company: str, tailored_summary: str) -> dict:
    """Build dynamic context dictionary for rendering resume_master.tex.j2."""
    p_info = cv_profile.get("personal_info", {})
    personal_info = {
        "name": escape_latex(p_info.get("name", "Sourav Ray")),
        "location": escape_latex(p_info.get("location", "Bengaluru, India")),
        "phone": escape_latex(p_info.get("phone", "+91-7872567781")),
        "email": escape_latex(p_info.get("email", "sroy.dgp2014@gmail.com")),
        "linkedin": p_info.get("linkedin", "linkedin.com/in/souravray17").replace("https://", "").replace("http://", ""),
        "github": p_info.get("github", "github.com/SouravRay17").replace("https://", "").replace("http://", "")
    }

    target_headline = select_target_headline(job_title, cv_profile)

    technical_skills = [
        {"category": "Programming \\& Analysis", "skills": "Python (pandas, NumPy, scikit-learn), SQL (advanced, large-scale), Shell Scripting"},
        {"category": "Statistics \\& ML", "skills": r"Regression and classification, EDA, outlier detection (Z-score/IQR), time-series forecasting, hypothesis testing (t-test, p-value), MLE, PCA, mathematical optimization, model evaluation (RMSE, MAE, MAPE, R\textsuperscript{2})"},
        {"category": "Deep Learning", "skills": "TensorFlow, Keras, Transformers (self-attention), LSTM/GRU/Bi-LSTM, 1D CNN"},
        {"category": "GenAI \\& LLMs", "skills": "LLM agents, RAG, Model Context Protocol (MCP), multi-agent orchestration, prompt engineering, Snowflake Cortex, hybrid retrieval and reranking"},
        {"category": "Cloud \\& Data", "skills": "GCP (BigQuery, Vertex AI), Snowflake (Snowpark, Snowpipe), AWS (S3, Lambda, Kinesis, DMS), DBT, Airflow, Kafka, CDC, data contracts and data quality"},
        {"category": "Tools \\& DevOps", "skills": "Git, GitHub Actions, Docker, Kubernetes, Terraform/CDKTF"}
    ]

    senior_analyst_projects = [
        {
            "name": "Snowflake Cost Optimization Agent",
            "period": "May 2026 -- Present",
            "bullets": [
                r"Cut Snowflake compute cost by \textbf{65\%} across 60 DBT models and 70 virtual warehouses by profiling queries (disk spillage, Cartesian joins) and tuning warehouse auto-suspend and right-sizing.",
                r"Built an autonomous LLM agent (Snowflake Cortex, Snowpark, DBT, MCP) that diagnoses cost anomalies and automates fix recommendations via GitHub pull requests and Jira tickets as Lead Engineer.",
                r"Designed a three-part validation suite (row count, column count, MD5 hash diffing) run pre- and post-change, with post-deployment telemetry to verify savings without data drift.",
                r"Automated RBAC and account-level parameter management across dev, staging, and production using Terraform and staged rollouts."
            ]
        },
        {
            "name": "AI-Powered Network Incident Orchestrator",
            "period": "Jan 2026 -- Present",
            "bullets": [
                r"Reduced MTTD by \textbf{60\%} and MTTR by \textbf{65\%} using a multi-agent AI system: one orchestrator directing five specialist sub-orchestrators for automated troubleshooting and diagnostics.",
                r"Correlated incidents, telemetry, topology, and change history across 20+ enterprise tools (ServiceNow, Datadog, Splunk, NetBox, PagerDuty) into a single LLM-generated root-cause summary.",
                r"Built and deployed Python MCP servers on Kubernetes with workload autoscaling; integrated automated incident summaries into ServiceNow and Microsoft Teams bridges."
            ]
        }
    ]

    analyst_projects = [
        {
            "name": r"Customer 360 Data Mesh \& Governance Platform",
            "period": "Sep 2023 -- Dec 2025",
            "bullets": [
                r"Architected Bronze/Silver/Gold lakehouse layers across 100--200 DBT/SQL models for a petabyte-scale Customer 360 platform integrating 1,000+ sources across five patterns.",
                r"Improved data accessibility by \textbf{60\%} through governed data products, multi-stage reconciliation, and contract-driven onboarding.",
                r"Cut data modeling effort by \textbf{80\%} via metadata-driven code generation, automating data contract creation for 100+ tables in ~10 minutes.",
                r"Ingested ~500 tables from Oracle, MySQL, MariaDB, and PostgreSQL via AWS DMS (full load + CDC) with zero data loss using LSN handoffs and automated Snowpipe streaming.",
                r"Accelerated CI/CD delivery with Terraform/CDKTF and GitHub Actions, deploying ephemeral per-PR test environments to validate changes before merge."
            ]
        }
    ]

    independent_projects = [
        {
            "name": r"Job Discovery \& Retrieval Pipeline -- Automated ATS Ingestion Engine (Independent, GitHub)",
            "period": "",
            "bullets": [
                r"Built an automated ETL pipeline ingesting live job postings from ATS APIs (Greenhouse, Lever, Ashby, Workday), normalizing semi-structured metadata into SQLite with deduplication.",
                r"Built a high-recall hybrid retrieval engine (Dense embeddings + BM25) with Reciprocal Rank Fusion (RRF), Cross-Encoder reranking, and MMR diversification (Top-100 $\rightarrow$ Top-20 $\rightarrow$ Top-10--15).",
                r"Automated daily batch execution via GitHub Actions, running IR evaluation (Recall@K, NDCG@K, MRR), candidate-job fit scoring, and dynamic LaTeX/PDF resume tailoring."
            ]
        },
        {
            "name": r"Spatio-Temporal Air Pollution Prediction using a Transformer (M.Tech Thesis)",
            "period": "May 2023",
            "bullets": [
                r"Designed an encoder-only Transformer with masked-value pre-training to forecast PM2.5, PM10, SO\textsubscript{2}, and NO\textsubscript{2} on Beijing AQI data (TensorFlow, Keras, scikit-learn).",
                r"Outperformed GRU, LSTM, Bi-LSTM, and CNN baselines with highest R\textsuperscript{2} across all 4 pollutants (up to 0.986 on NO\textsubscript{2}), confirmed statistically by residual t-tests.",
                r"Built full data pipeline: outlier detection (Z-score/IQR/Tukey), rolling windows, normalization, and Pearson spatial-correlation analysis across 12 monitoring stations."
            ]
        }
    ]

    education = [
        {
            "institution": "National Institute of Technology (NIT), Durgapur",
            "years": "2021 -- 2023",
            "degree": "M.Tech, Operations Research",
            "grade": "CGPA 8.36/10"
        },
        {
            "institution": "Government College of Engineering and Textile Technology",
            "years": "2015 -- 2019",
            "degree": "B.Tech, Textile Technology",
            "grade": "CGPA 7.43/10"
        }
    ]

    certifications_line = (
        r"Google Cloud Professional Data Engineer \textbar{} Snowflake SnowPro Advanced Data Scientist \textbar{} "
        r"AWS Certified Machine Learning -- Specialty \textbar{} Snowflake SnowPro Advanced Architect \textbar{} "
        r"AWS Certified Solutions Architect -- Associate"
    )

    return {
        "personal_info": personal_info,
        "target_headline": escape_latex(target_headline),
        "tailored_summary": escape_latex(tailored_summary),
        "technical_skills": technical_skills,
        "company_name": "Factspan Analytics",
        "company_location": "Bengaluru, India",
        "current_title": "Senior Analyst",
        "current_period": "Sep 2025 -- Present",
        "previous_title": "Analyst",
        "previous_period": "Sep 2023 -- Aug 2025",
        "senior_analyst_projects": senior_analyst_projects,
        "analyst_projects": analyst_projects,
        "independent_projects": independent_projects,
        "education": education,
        "certifications_line": certifications_line
    }


def render_latex_from_profile(cv_profile: dict, summary_text: str, job_title: str = "", company: str = "") -> str | None:
    """Dynamically render the LaTeX resume using the Jinja2 template engine."""
    try:
        template = latex_jinja_env.get_template("resume_master.tex.j2")
        context = build_resume_context(cv_profile, job_title, company, summary_text)
        return template.render(**context)
    except Exception as e:
        print(f"  [!] Jinja2 resume rendering failed: {e}")
        return None


def render_cover_letter_latex(cv_profile: dict, job_title: str, company: str, cover_letter_text: str) -> str | None:
    """Dynamically render a tailored cover letter using the Jinja2 template engine."""
    try:
        template = latex_jinja_env.get_template("cover_letter_master.tex.j2")
        p_info = cv_profile.get("personal_info", {})
        personal_info = {
            "name": escape_latex(p_info.get("name", "Sourav Ray")),
            "location": escape_latex(p_info.get("location", "Bengaluru, India")),
            "phone": escape_latex(p_info.get("phone", "+91-7872567781")),
            "email": escape_latex(p_info.get("email", "sroy.dgp2014@gmail.com")),
            "linkedin": p_info.get("linkedin", "linkedin.com/in/souravray17").replace("https://", "").replace("http://", "")
        }
        # Format paragraphs for LaTeX
        paragraphs = [escape_latex(p.strip()) for p in cover_letter_text.split("\n\n") if p.strip()]
        body_latex = "\n\n".join(paragraphs)

        context = {
            "personal_info": personal_info,
            "target_headline": escape_latex(select_target_headline(job_title, cv_profile)),
            "current_date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
            "company": escape_latex(company),
            "job_title": escape_latex(job_title),
            "cover_letter_body": body_latex
        }
        return template.render(**context)
    except Exception as e:
        print(f"  [!] Jinja2 cover letter rendering failed: {e}")
        return None


def compile_pdf_resume(job_source: str, job_id: str) -> str | None:
    """Generate tailored resume and cover letter PDFs using Jinja2 and Tectonic."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
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
            """SELECT j.company, c.tailored_summary, j.title, c.cover_letter_draft
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
    cover_letter_text = row[3] if row and len(row) > 3 and row[3] else None

    # Fallback summary if LLM tailoring hasn't run yet
    if not summary_text:
        summary_text = (
            f"Data scientist with 3 years of experience building Python and SQL data and ML systems on AWS, "
            f"Snowflake and GCP, plus an M.Tech in Operations Research (NIT Durgapur) with a thesis on Transformer-based "
            f"regression (R^2 up to 0.986). Strong in EDA, statistical evaluation, and pre/post-change validation, and in "
            f"turning technical findings into business results: 65% lower Snowflake compute cost, 60% faster incident "
            f"detection (MTTD) and 65% faster resolution (MTTR) using LLM agents. Targeting the {title} role at {company}."
        )

    company_clean = re.sub(r'[^a-zA-Z0-9]', '_', company)

    # 1. Compile Tailored Resume PDF
    temp_tex_path = os.path.join(exports_dir, f"temp_cv_{company_clean}_{job_id}.tex")
    temp_pdf_path = os.path.join(exports_dir, f"temp_cv_{company_clean}_{job_id}.pdf")
    output_pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}.pdf")

    tex_content = render_latex_from_profile(cv_profile, summary_text, job_title=title, company=company)
    if not tex_content:
        return None

    try:
        with open(temp_tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        result = subprocess.run([tectonic_bin, temp_tex_path, "--outdir", exports_dir], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [!] Tectonic resume compilation returned {result.returncode}: {result.stderr or result.stdout}")

        if os.path.exists(temp_pdf_path):
            try:
                shutil.copy2(temp_pdf_path, output_pdf_path)
            except PermissionError:
                import time
                output_pdf_path = os.path.join(exports_dir, f"Sourav_Resume_{company_clean}_{job_id}_{int(time.time())}.pdf")
                shutil.copy2(temp_pdf_path, output_pdf_path)
    except Exception as e:
        print(f"  [!] Tectonic resume execution error: {e}")
        return None
    finally:
        for p in (temp_tex_path, temp_pdf_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # 2. Compile Tailored Cover Letter PDF (if draft available)
    if cover_letter_text:
        cl_tex_path = os.path.join(exports_dir, f"temp_cl_{company_clean}_{job_id}.tex")
        cl_temp_pdf = os.path.join(exports_dir, f"temp_cl_{company_clean}_{job_id}.pdf")
        cl_out_pdf = os.path.join(exports_dir, f"Sourav_Cover_Letter_{company_clean}_{job_id}.pdf")
        cl_content = render_cover_letter_latex(cv_profile, title, company, cover_letter_text)
        if cl_content:
            try:
                with open(cl_tex_path, "w", encoding="utf-8") as f:
                    f.write(cl_content)
                res_cl = subprocess.run([tectonic_bin, cl_tex_path, "--outdir", exports_dir], capture_output=True, text=True)
                if res_cl.returncode == 0 and os.path.exists(cl_temp_pdf):
                    shutil.copy2(cl_temp_pdf, cl_out_pdf)
            except Exception as e:
                print(f"  [!] Cover letter compilation error: {e}")
            finally:
                for p in (cl_tex_path, cl_temp_pdf):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

    print(f"  [OK] Tailored Resume PDF created: {output_pdf_path}")
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
