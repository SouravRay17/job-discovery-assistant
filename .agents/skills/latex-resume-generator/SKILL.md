---
name: latex-resume-generator
description: >-
  Maps structured candidate profile data (Sourav_Ray_Updated_Profile.yaml)
  to the master LaTeX resume template (Sourav_Ray_Resume_Master.tex) and compiles ATS-optimized
  PDF resumes using the Tectonic engine.
---

# LaTeX Resume Generator & Profile Mapping Skill

This skill defines the end-to-end workflow for reading Sourav Ray's master candidate profile (`Sourav_Ray_Updated_Profile.yaml`), selecting the optimal positioning persona, extracting matching technical skills, mapping them into the LaTeX template (`Sourav_Ray_Resume_Master.tex`), and compiling ATS-optimized PDF resumes via **Tectonic**.

---

## 🧑‍💻 Candidate Profile & Verified Skill Taxonomy

### 1. Generative AI, LLMs & Agentic Systems
- **LLM & Agentic Architecture**: Large Language Models (LLMs), Agentic AI, Multi-Agent Orchestration, Dynamic Agent Selection, Concurrency Control, In-memory Caching.
- **RAG & Search**: Retrieval-Augmented Generation (RAG) multi-layer architecture (Exact Match, Semantic Match, LLM Inference), Vector Search, ChromaDB, Snowflake Cortex.
- **Protocols & Frameworks**: Model Context Protocol (MCP) server development (integrations with GitHub, Jira, Airtable, ServiceNow, Infoblox, NetBox, SevOne, Datadog, Splunk, LogicMonitor, Snowflake), LangChain, LangGraph, Ollama, OpenAI, Google Gemini.
- **Engineering & Safety**: Prompt Engineering, Context Engineering, LLM Evaluation, Guardrails, Responsible AI Governance (PII detection & exclusion).
- **NLP & Audio**: NLP-powered chatbots, Semantic Querying, Real-time Speech-to-Text / Meeting Intelligence (CallAI).

### 2. Core Data Engineering & Distributed Systems
- **Languages**: Python, SQL, PySpark, Bash/Shell.
- **Processing & Streaming**: Apache Spark / PySpark, Kafka, RabbitMQ, Distributed Processing, High-Volume Data Ingestion.
- **Pipelines & Lakehouse**: DBT (transformation models & testing), Apache Airflow (DAG orchestration), Coalesce, Apache Iceberg (open table formats), Snowpipe, AWS DMS.
- **Architecture**: Data Mesh, Data Contracts, Bronze/Silver/Gold Lakehouse Architecture, Customer 360, Data Warehousing, Dimensional Data Modeling.
- **Data Quality & Governance**: Automated Data Contract Evaluators, Multi-stage Reconciliation (Row-count, Column-count, MD5 hash verification), Schema Drift Detection, Audit-Ready Validation Controls.

### 3. Cloud & Data Platforms
- **Snowflake Platform Engineering**: Snowpark (Python/Pandas), Snowpipe, Snowflake Cortex, Time Travel, Zero-Copy Cloning, Virtual Warehouse Right-Sizing, Auto-Suspend/Resume Tuning, Query Profiling (Disk Spillage, Cartesian Joins, Search Optimization Service), RBAC & Multi-Environment Parameters.
- **AWS Cloud**: S3, Lambda, Kinesis, Kinesis Firehose, Database Migration Service (DMS), CloudWatch, IAM.
- **GCP**: Vertex AI, BigQuery.
- **Infrastructure as Code**: Terraform.

### 4. Software Engineering & MLOps
- **Containers & DevOps**: Docker, Kubernetes, Git, GitHub Actions, CI/CD Pipelines, ArgoCD / GitOps.
- **MLOps**: Model Deployment, Evaluation, Latency Optimization, Production Monitoring.
- **BI & Analytics**: Sigma (Lineage & Analytics), SAP BusinessObjects validation.

### 5. Theoretical Foundations & Algorithms (M.Tech Operations Research)
- Advanced Algorithms, Dynamic Programming, Divide & Conquer, Greedy Algorithms, Graph Algorithms, Network Flow.
- NP-Completeness, Approximation Algorithms, Randomized Algorithms, Mathematical Foundations of Machine Learning, Optimization Techniques.

### 6. Industry Certifications
1. **Snowflake SnowPro Advanced Architect**
2. **Snowflake SnowPro Advanced Data Scientist**
3. **AWS Certified Machine Learning – Specialty**
4. **AWS Certified Solutions Architect – Associate**

---

## 🎯 Positioning Personas & Targeting Strategy

When tailoring a resume for a target job description, select the primary persona from `Sourav_Ray_Updated_Profile.yaml`:

| Persona ID | Headline & Focus | Target Roles | Key Projects to Emphasize |
| :--- | :--- | :--- | :--- |
| `genai_agentic_lead` | **AI & GenAI Engineer \| Agentic AI & RAG Systems \| Data Platform Architecture** | GenAI Engineer, Agentic AI Engineer, LLM Engineer, AI Platform Lead | AI Network Incident Orchestrator (MCP), Snowflake Cost Optimization Agent, GenAI Schema Validator |
| `snowflake_platform_engineer` | **Data Engineer \| Snowflake Platform Engineering \| GenAI & Agentic AI Systems** | Snowflake Data Engineer, Cloud Data Platform Engineer, Data Lead | Snowflake Cost Optimization Agent (65% cost cut), Customer 360 Data Mesh (Iceberg, Snowpipe) |
| `software_ml_infra` | **Software Engineer \| AI & Data Engineer \| ML Infrastructure \| GenAI** | Software Engineer, ML Infra Engineer, Backend Engineer | AI Network Incident Orchestrator (CallAI, Python MCP codebase), Data Pipeline CI/CD, Algorithms background |
| `ai_data_engineer_generalist` | **AI & Data Engineer \| GenAI & Agentic AI \| ML & Data Engineering** | General AI/Data Engineer, Recruiter screening, Data Architect | Combined Highlights: 65% Snowflake cost cut + 60% MTTD incident reduction + Petabyte Data Mesh |
| `customer_data_ml` | **AI & Data Engineer \| Technical Lead \| GenAI \| Customer Data & ML** | Customer 360, Analytics Lead, Data Governance Lead | Customer 360 Data Mesh (1,000+ sources), Data Contract Evaluator, Data-Powered Assist Chatbot |

---

## 🏆 Key Headline Achievements (Quantified Proof Points)

Always preserve these high-impact metric anchors across tailored resumes:
1. **65% Snowflake Compute-Cost Reduction** across 60 DBT models and 70 virtual warehouses via warehouse right-sizing and LLM-driven query remediation.
2. **60% MTTD & 65% MTTR Reduction** via multi-agent AI incident orchestrator across ServiceNow, Datadog, Splunk, Infoblox, and SevOne.
3. **Petabyte-Scale Customer 360 Platform** integrating 1,000+ data sources across 5 ingestion patterns with 60% improvement in enterprise data accessibility.
4. **80% Development Effort Reduction** via metadata-driven automation for Bronze/Silver table definitions, DBT models, and data-contract generation (100 contracts in ~10 mins).
5. **Fast-Track Promotion within 2 Years** at Factspan Analytics (Analyst → Senior Analyst) for taking on technical leadership across GenAI, Agentic AI, and data platform delivery.

---

## 📝 LaTeX Template Mapping & Injection Rules

Master LaTeX File: `Sourav_Ray_Resume_Master.tex`

### 1. LaTeX Character Escaping
All text inserted into LaTeX must pass through character translation to prevent compilation failures:

```python
LATEX_TRANS = str.maketrans({
    '&': r'\&',
    '%': r'\%',
    '_': r'\_',
    '$': r'\$',
    '#': r'\#',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
})

def escape_latex(text: str) -> str:
    if not text:
        return ""
    escaped = text.translate(LATEX_TRANS)
    import re
    return re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', escaped)
```

### 2. Section Injection Mapping
1. **Professional Summary**:
   - Synthesize 3-4 sentences aligned with the target role and candidate persona.
   - Insert as `\section*{Professional Summary}` immediately above `\section*{Highlights}` or after `\begin{document}`.
2. **Highlights**:
   - Select 5-6 top bullet points directly addressing the core requirements in the target Job Description.
3. **Technical Skills**:
   - Map into the 5 structured groups: `Cloud & Data Platforms`, `Data Engineering`, `AI / ML & GenAI`, `Programming`, and `Tools`.
4. **Experience & Projects**:
   - Format company, titles, and dates:
     `\textbf{Factspan Analytics, Bengaluru}`
     `\textit{Senior Analyst (Sep 2025 -- Present) | Analyst (Sep 2023 -- Sep 2025)}`
   - Select top 2-3 most relevant projects and their quantified bullet points.
5. **Education & Certifications**:
   - NIT Durgapur (M.Tech, Operations Research, CGPA: 8.36/10, 2021--2023)
   - GCETTB (B.Tech, 2015--2019)
   - Snowflake & AWS Certifications.

---

## ⚡ Compilation & Execution Workflow

### Step 1: Create Temporary `.tex`
Generate `exports/temp_cv_<company>_<job_id>.tex` with escaped dynamic content.

### Step 2: Compile via Tectonic Engine
```powershell
# Windows
.\tectonic.exe exports/temp_cv_<company>_<job_id>.tex --outdir exports/

# Linux / Mac / CI
tectonic exports/temp_cv_<company>_<job_id>.tex --outdir exports/
```

### Step 3: Rename & Verify
- Output PDF is moved to `exports/Sourav_Resume_<company>_<job_id>.pdf`.
- Clean up temporary `.tex` files.
- Verify file existence and non-zero byte size.

### Built-in Automation CLI:
```bash
# Tailor single job:
python tailor.py --source greenhouse:stripe --id 12345

# Batch tailor top qualifying openings:
python tailor.py --batch --top 10
```

---

## 🔒 Hard Constraints
- **Zero Fabrication**: Ground every claim strictly in `Sourav_Ray_Updated_Profile.yaml` and `cv_profile.json`.
- **ATS Formatting**: Single-column layout, standard margins, no tables/graphics that block ATS parsers.
- **Date Consistency**: Use `YYYY-MM` or `Month YYYY` standard formats.
