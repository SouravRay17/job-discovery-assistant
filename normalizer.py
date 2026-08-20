"""
normalizer.py — Deterministic structured metadata extraction & search document generation.

Extracts:
  - required_skills, preferred_skills
  - experience_min, experience_max
  - role_family, domain
  - employment_type, remote_type, education, certifications
  - search_text (high-signal concise document for embedding & BM25 indexing)

Runs incrementally on jobs where normalized_at IS NULL.
"""

import json
import os
import re
from datetime import datetime, timezone
from config import load_config
from db import get_connection, init_db
from scraper import fetch_greenhouse_description, fetch_workday_description


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Skill Taxonomy & Normalization Map
# ---------------------------------------------------------------------------

SKILL_TAXONOMY = {
    # Programming Languages
    "python": "Python",
    "sql": "SQL",
    "pyspark": "PySpark",
    "scala": "Scala",
    "java": "Java",
    "c++": "C++",
    "golang": "Go",
    "rust": "Rust",
    "bash": "Shell Scripting",
    "shell": "Shell Scripting",
    "typescript": "TypeScript",
    "javascript": "JavaScript",

    # Data Warehouses & Platforms
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "redshift": "Redshift",
    "databricks": "Databricks",
    "clickhouse": "ClickHouse",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "dynamodb": "DynamoDB",
    "cassandra": "Cassandra",

    # Data Engineering & Orchestration
    "dbt": "dbt",
    "airflow": "Apache Airflow",
    "apache airflow": "Apache Airflow",
    "kafka": "Apache Kafka",
    "apache kafka": "Apache Kafka",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "flink": "Apache Flink",
    "coalesce": "Coalesce",
    "etl": "ETL/ELT",
    "elt": "ETL/ELT",
    "data pipeline": "Data Pipelines",
    "data pipelines": "Data Pipelines",
    "data modeling": "Data Modeling",
    "data contracts": "Data Contracts",
    "data mesh": "Data Mesh",
    "data lakehouse": "Lakehouse",
    "lakehouse": "Lakehouse",
    "pandas": "Pandas",
    "polars": "Polars",
    "iceberg": "Apache Iceberg",
    "delta lake": "Delta Lake",

    # Cloud Platforms & Services
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "s3": "AWS S3",
    "lambda": "AWS Lambda",
    "kinesis": "AWS Kinesis",
    "firehose": "AWS Firehose",
    "glue": "AWS Glue",
    "emr": "AWS EMR",
    "athena": "AWS Athena",
    "vertex ai": "Vertex AI",
    "sagemaker": "SageMaker",
    "cloud functions": "GCP Cloud Functions",

    # AI, ML & Generative AI
    "llm": "LLMs",
    "llms": "LLMs",
    "large language model": "LLMs",
    "large language models": "LLMs",
    "genai": "Generative AI",
    "generative ai": "Generative AI",
    "rag": "RAG",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "llamaindex": "LlamaIndex",
    "vector search": "Vector Search",
    "vector db": "Vector Databases",
    "chromadb": "ChromaDB",
    "pinecone": "Pinecone",
    "weaviate": "Weaviate",
    "qdrant": "Qdrant",
    "faiss": "FAISS",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "scikit-learn": "Scikit-Learn",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "computer vision": "Computer Vision",
    "mlops": "MLOps",
    "huggingface": "HuggingFace",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "anthropic": "Anthropic",
    "model context protocol": "MCP",
    "mcp": "MCP",
    "multi-agent": "Multi-Agent Systems",
    "agentic": "Agentic AI",
    "fine-tuning": "Fine-Tuning",
    "prompt engineering": "Prompt Engineering",

    # DevOps, Tools & Infra
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "git": "Git",
    "github actions": "GitHub Actions",
    "ci/cd": "CI/CD",
    "terraform": "Terraform",
    "linux": "Linux",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "rest api": "REST APIs",
    "grpc": "gRPC",
    "graphql": "GraphQL",

    # BI & Analytics
    "sigma": "Sigma",
    "tableau": "Tableau",
    "power bi": "PowerBI",
    "powerbi": "PowerBI",
    "looker": "Looker",
    "superset": "Superset",
}


def extract_skills_from_text(text: str) -> list[str]:
    """Identify canonical skills present in text using boundary-checked matching."""
    if not text:
        return []
    text_lower = f" {text.lower()} "
    found_skills = set()

    for pattern, canonical in SKILL_TAXONOMY.items():
        # Match word boundaries or punctuation borders
        escaped = re.escape(pattern)
        if re.search(rf"(?:\b|(?<=[^a-zA-Z0-9])){escaped}(?:\b|(?=[^a-zA-Z0-9]))", text_lower):
            found_skills.add(canonical)

    return sorted(found_skills)


def extract_experience(text: str) -> tuple[float | None, float | None]:
    """Extract minimum and maximum years of experience required from text."""
    if not text:
        return None, None

    # Pattern: 3-5 years, 3 to 5 years, 3 - 5 yrs
    range_match = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*(?:years?|yrs?)", text, re.IGNORECASE)
    if range_match:
        try:
            min_yr = float(range_match.group(1))
            max_yr = float(range_match.group(2))
            if 0 <= min_yr <= 30 and 0 <= max_yr <= 30:
                return min_yr, max_yr
        except ValueError:
            pass

    # Pattern: 3+ years, 3+ yrs, minimum 3 years, at least 3 years
    min_match = re.search(r"(?:minimum|at least|\b)(\d+)\s*(?:\+|plus)?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+experience|\s+exp)?", text, re.IGNORECASE)
    if min_match:
        try:
            min_yr = float(min_match.group(1))
            if 0 <= min_yr <= 30:
                return min_yr, None
        except ValueError:
            pass

    return None, None


def classify_role_family(title: str, description: str) -> str:
    """Classify job into standard role families."""
    combined = f"{title} {description[:300]}".lower()

    if any(k in combined for k in ["ai engineer", "ai developer", "generative ai", "genai", "llm engineer", "machine learning", "ml engineer", "mlops", "nlp"]):
        return "AI/ML Engineering"
    elif any(k in combined for k in ["data engineer", "data engineering", "data platform", "pyspark", "snowflake", "etl", "analytics engineer", "dbt"]):
        return "Data Engineering"
    elif any(k in combined for k in ["backend engineer", "python developer", "software engineer", "software developer", "backend developer"]):
        return "Software Engineering"
    elif any(k in combined for k in ["data scientist", "applied scientist", "research scientist", "statistician"]):
        return "Data Science"
    elif any(k in combined for k in ["devops", "cloud engineer", "site reliability", "sre", "platform engineer"]):
        return "Cloud & Infrastructure"
    return "Data & AI Engineering"


def classify_domain(title: str, description: str, company: str) -> str:
    """Determine domain context for high-signal retrieval."""
    combined = f"{title} {description[:500]} {company}".lower()

    if any(k in combined for k in ["genai", "generative ai", "llm", "rag", "agents", "langchain", "prompt"]):
        return "Generative AI"
    elif any(k in combined for k in ["mlops", "model serving", "feature store", "ml infra", "training pipeline"]):
        return "ML Infrastructure"
    elif any(k in combined for k in ["data warehouse", "lakehouse", "data platform", "snowflake", "bigquery", "dbt", "datapipeline"]):
        return "Data Platforms"
    elif any(k in combined for k in ["finance", "fintech", "banking", "payments", "accounting", "ledger"]):
        return "FinTech & Financial Data"
    elif any(k in combined for k in ["analytics", "reporting", "bi ", "business intelligence", "metrics"]):
        return "Enterprise Analytics"
    return "Cloud & Enterprise Data"


def determine_remote_type(location: str, title: str, description: str, is_remote_flag: bool) -> str:
    """Determine remote classification."""
    combined = f"{location} {title} {description[:200]}".lower()
    if is_remote_flag or "remote" in combined or "anywhere" in combined or "worldwide" in combined:
        return "Remote"
    elif "hybrid" in combined:
        return "Hybrid"
    return "On-site"


def split_required_and_preferred(description: str) -> tuple[list[str], list[str]]:
    """Segment description into Required vs Preferred skill sets."""
    if not description:
        return [], []

    # Look for Preferred / Nice to have section
    preferred_split = re.split(r"(?:preferred qualifications|nice to have|bonus points|preferred skills|desired qualifications|plus if you have):?", description, flags=re.IGNORECASE)
    
    if len(preferred_split) > 1:
        req_text = preferred_split[0]
        pref_text = " ".join(preferred_split[1:])
        required_skills = extract_skills_from_text(req_text)
        preferred_skills = [s for s in extract_skills_from_text(pref_text) if s not in required_skills]
    else:
        required_skills = extract_skills_from_text(description)
        preferred_skills = []

    return required_skills, preferred_skills


def build_search_text(
    title: str,
    company: str,
    role_family: str,
    domain: str,
    required_skills: list[str],
    preferred_skills: list[str],
    exp_min: float | None,
    location: str,
    remote_type: str,
    raw_desc: str
) -> str:
    """Create a high-signal search document for embedding and BM25 indexing."""
    req_str = ", ".join(required_skills) if required_skills else "General technical skills"
    pref_str = ", ".join(preferred_skills) if preferred_skills else "None specified"
    exp_str = f"{int(exp_min)}+ years" if exp_min is not None else "Not specified"

    # Extract 2-3 key sentences from raw description
    clean_lines = [line.strip() for line in (raw_desc or "").split("\n") if len(line.strip()) > 30 and not line.strip().startswith(("#", "*", "-"))]
    summary_excerpt = " ".join(clean_lines[:3])[:400] if clean_lines else (raw_desc or "")[:300]

    return f"""Title: {title}
Company: {company}
Role: {role_family}
Domain: {domain}
Required Skills: {req_str}
Preferred Skills: {pref_str}
Experience: {exp_str}
Location: {location} ({remote_type})
Summary: {summary_excerpt}"""


def normalize_job_record(job: dict) -> dict:
    """Transform raw job row into structured normalized metadata."""
    title = job.get("title") or "Untitled"
    company = job.get("company") or "Unknown"
    location = job.get("location") or ""
    remote_flag = bool(job.get("remote"))
    raw_desc = job.get("description_raw") or ""

    role_family = classify_role_family(title, raw_desc)
    domain = classify_domain(title, raw_desc, company)
    remote_type = determine_remote_type(location, title, raw_desc, remote_flag)
    required_skills, preferred_skills = split_required_and_preferred(raw_desc)
    exp_min, exp_max = extract_experience(raw_desc)

    search_text = build_search_text(
        title=title,
        company=company,
        role_family=role_family,
        domain=domain,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        exp_min=exp_min,
        location=location,
        remote_type=remote_type,
        raw_desc=raw_desc
    )

    return {
        "source": job["source"],
        "id": job["id"],
        "search_text": search_text,
        "required_skills": json.dumps(required_skills),
        "preferred_skills": json.dumps(preferred_skills),
        "role_family": role_family,
        "domain": domain,
        "experience_min": exp_min,
        "experience_max": exp_max,
        "education": "Degree in Computer Science, Engineering or related technical field",
        "certifications": "Cloud/Data Certifications preferred",
        "employment_type": "Full-time",
        "remote_type": remote_type,
        "normalized_at": now_iso(),
    }


def normalize_jobs():
    """Batch normalize all unscored/un-normalized jobs in SQLite."""
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT source, id, company, title, location, remote, url, description_raw "
            "FROM jobs WHERE normalized_at IS NULL"
        )
        unnormalized = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not unnormalized:
        print("[*] All jobs in jobs.db are already normalized.")
        return 0

    print(f"\n{'='*60}\nJob Normalizer -- Processing {len(unnormalized)} New/Changed Listings\n{'='*60}")
    normalized_count = 0

    conn = get_connection()
    try:
        for i, job in enumerate(unnormalized, 1):
            source = job["source"]
            job_id = job["id"]
            title = job["title"]
            company = job["company"]
            desc = job["description_raw"]

            # Lazy hydrate description if missing
            if not desc:
                if source.startswith("greenhouse:"):
                    board = source.split(":", 1)[1]
                    desc = fetch_greenhouse_description(board, job_id)
                elif source.startswith("workday:"):
                    slug = source.split(":", 1)[1]
                    desc = fetch_workday_description(slug, job_id)

                if desc:
                    conn.execute("UPDATE jobs SET description_raw = ? WHERE source = ? AND id = ?", (desc, source, job_id))
                    job["description_raw"] = desc

            norm = normalize_job_record(job)

            conn.execute(
                """UPDATE jobs
                   SET search_text = ?, required_skills = ?, preferred_skills = ?,
                       role_family = ?, domain = ?, experience_min = ?, experience_max = ?,
                       education = ?, certifications = ?, employment_type = ?, remote_type = ?,
                       normalized_at = ?
                   WHERE source = ? AND id = ?""",
                (
                    norm["search_text"], norm["required_skills"], norm["preferred_skills"],
                    norm["role_family"], norm["domain"], norm["experience_min"], norm["experience_max"],
                    norm["education"], norm["certifications"], norm["employment_type"], norm["remote_type"],
                    norm["normalized_at"], source, job_id
                )
            )
            normalized_count += 1
            if i % 50 == 0 or i == len(unnormalized):
                print(f"  Normalized {i}/{len(unnormalized)}: {title} at {company}")

        conn.commit()
    finally:
        conn.close()

    print(f"\n[OK] Normalization completed for {normalized_count} jobs.\n")
    return normalized_count


if __name__ == "__main__":
    normalize_jobs()
