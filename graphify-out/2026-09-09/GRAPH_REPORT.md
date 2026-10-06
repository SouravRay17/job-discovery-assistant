# Graph Report - job-discovery-assistant  (2026-08-21)

## Corpus Check
- Corpus is ~19,365 words - fits in a single context window. You may not need a graph.

## Summary
- 211 nodes · 449 edges · 12 communities (11 shown, 1 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 17 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Resume Tailoring & LaTeX Compilation
- Multi-Source Job Scraper
- Candidate Profile & On-Demand Tailoring
- Unified LLM Client
- Job Normalization & Skill Extraction
- Cross-Encoder Reranking & MMR
- Email Digest & Notifications
- Information Retrieval Evaluation Suite
- Hybrid Retrieval & Scoring Engine
- Streamlit Dashboard & SQLite Storage
- Vector Embeddings & BM25 Indexer
- Graphify Knowledge Graph & Agent Workflows

## God Nodes (most connected - your core abstractions)
1. `get_connection()` - 28 edges
2. `init_db()` - 24 edges
3. `load_config()` - 21 edges
4. `retrieve_jobs()` - 19 edges
5. `rerank_jobs()` - 12 edges
6. `run_batch_tailoring()` - 12 edges
7. `run_pipeline()` - 11 edges
8. `tailor_job()` - 11 edges
9. `Sourav Ray Master Candidate Profile` - 11 edges
10. `load_candidate_profile()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Tailored Resume PDF: Company 102 Data & AI Engineer` --implements--> `LaTeX Resume Generator Skill`  [INFERRED]
  exports/Sourav_Resume_Company_102.pdf → .agents/skills/latex-resume-generator/SKILL.md
- `Tailored Resume PDF: Affirm Senior Software Engineer Backend` --references--> `AI-Powered Network Incident Orchestrator`  [INFERRED]
  exports/Sourav_Resume_Affirm_7820446003.pdf → Sourav_Ray_Updated_Profile.yaml
- `Tailored Resume PDF: Affirm Senior Software Engineer Backend` --references--> `GenAI Schema Validator & Automated Mapping`  [INFERRED]
  exports/Sourav_Resume_Affirm_7820446003.pdf → Sourav_Ray_Updated_Profile.yaml
- `Tailored Resume PDF: Affirm Senior Software Engineer Backend` --implements--> `LaTeX Resume Generator Skill`  [INFERRED]
  exports/Sourav_Resume_Affirm_7820446003.pdf → .agents/skills/latex-resume-generator/SKILL.md
- `Tailored Resume PDF: Company 101 Data & AI Engineer` --implements--> `LaTeX Resume Generator Skill`  [INFERRED]
  exports/Sourav_Resume_Company_101.pdf → .agents/skills/latex-resume-generator/SKILL.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Resume Generation and PDF Export Pipeline** — _agents_skills_latex_resume_generator_skill_latex_resume_generator, sourav_ray_updated_profile_candidate_profile, exports_sourav_resume_affirm_7820446003_pdf, exports_sourav_resume_company_101_pdf [INFERRED 0.95]
- **Sourav Ray Enterprise Portfolio Projects** — sourav_ray_updated_profile_snowflake_cost_optimization_agent, sourav_ray_updated_profile_ai_network_incident_orchestrator, sourav_ray_updated_profile_customer_360_data_mesh, sourav_ray_updated_profile_genai_schema_validator [EXTRACTED 1.00]
- **Retrieval-First Job Discovery Architecture Pipeline** — readme_job_discovery_assistant_system, readme_hybrid_retrieval_pipeline, readme_cross_encoder_reranking, readme_blended_scoring [EXTRACTED 1.00]

## Communities (12 total, 1 thin omitted)

### Community 0 - "Resume Tailoring & LaTeX Compilation"
Cohesion: 0.10
Nodes (26): LaTeX Character Escaping Function, LaTeX Resume Generator Skill, Resume Positioning Personas Taxonomy, LaTeX Section Injection Mapping, Tectonic Resume Compilation Workflow, Job Discovery Scheduled Action Job, Daily Job Discovery & Auto-Tailoring CI/CD Workflow, Tailored Resume PDF: Affirm Timestamped Build (+18 more)

### Community 1 - "Multi-Source Job Scraper"
Cohesion: 0.15
Nodes (25): load_ats_mapping(), Load company ATS mapping from company_ats_mapping.toml., fetch_greenhouse(), fetch_lever(), fetch_linkedin(), fetch_naukri(), fetch_remoteok(), fetch_workday() (+17 more)

### Community 2 - "Candidate Profile & On-Demand Tailoring"
Cohesion: 0.13
Nodes (23): load_candidate_profile(), Load candidate profile from Sourav_Ray_Updated_Profile.yaml., fetch_greenhouse_description(), fetch_workday_description(), Fetch full job description from Greenhouse detail endpoint on demand., Fetch full job description from Workday detail endpoint on demand., clean_date(), compile_pdf_resume() (+15 more)

### Community 3 - "Unified LLM Client"
Cohesion: 0.14
Nodes (19): get_provider(), parse_json_from_llm(), _query_gemini(), query_llm(), _query_ollama(), llm_client.py — Unified LLM abstraction layer (Ollama local & Google Gemini…, Determine which LLM provider to use., Send a prompt to the configured LLM provider and return raw text response. (+11 more)

### Community 4 - "Job Normalization & Skill Extraction"
Cohesion: 0.14
Nodes (20): build_search_text(), classify_domain(), classify_role_family(), determine_remote_type(), extract_experience(), extract_skills_from_text(), normalize_job_record(), normalize_jobs() (+12 more)

### Community 5 - "Cross-Encoder Reranking & MMR"
Cohesion: 0.17
Nodes (14): config.py — Centralized configuration and YAML candidate profile loader using…, evaluate.py — Information Retrieval (IR) benchmarking & evaluation suite.…, apply_mmr_diversification(), compute_cross_encoder_scores(), get_cross_encoder(), now_iso(), reranker.py — Deep Cross-Encoder reranker and MMR diversification engine.…, Rerank retrieved candidates with Cross-Encoder and apply MMR diversification. (+6 more)

### Community 6 - "Email Digest & Notifications"
Cohesion: 0.21
Nodes (14): auto_populate_config(), load_config(), Load configuration from config.toml., Auto-populate config with boards from company_ats_mapping.toml., now_iso(), email_notifier.py — Send daily job digest and attached tailored PDF resumes via…, send_email_digest(), run_pipeline.py — Master orchestrator for the Retrieval-First Job Discovery… (+6 more)

### Community 7 - "Information Retrieval Evaluation Suite"
Cohesion: 0.13
Nodes (15): compute_dcg_at_k(), compute_mrr(), compute_ndcg_at_k(), compute_precision_at_k(), compute_recall_at_k(), evaluate_against_database(), generate_synthetic_benchmark_dataset(), main() (+7 more)

### Community 8 - "Hybrid Retrieval & Scoring Engine"
Cohesion: 0.19
Nodes (14): check_hard_filters(), compute_domain_score(), compute_experience_score(), compute_role_score(), compute_skill_overlap(), now_iso(), retriever.py — High-precision hybrid retrieval engine (Vector + BM25 + RRF +…, Calculate similarity of job title and role family to target roles. (+6 more)

### Community 9 - "Streamlit Dashboard & SQLite Storage"
Cohesion: 0.25
Nodes (12): Connection, load_data_from_db(), main(), dashboard.py — Streamlit review dashboard for the Retrieval-First Job Discovery…, Retrieve scored candidates joined with normalized job data from SQLite., get_connection(), init_db(), _migrate_db() (+4 more)

### Community 10 - "Vector Embeddings & BM25 Indexer"
Cohesion: 0.20
Nodes (13): build_bm25_document(), compute_embeddings(), get_embedding_model(), index_jobs(), now_iso(), indexer.py — Embedding generation & BM25 indexing for normalized jobs.…, Lazy load sentence transformer embedding model., Generate dense embeddings for a list of text strings. (+5 more)

## Knowledge Gaps
- **14 isolated node(s):** `Graphify Knowledge Graph Rule`, `LaTeX Character Escaping Function`, `LaTeX Section Injection Mapping`, `Graphify Extraction Workflow`, `Hybrid Retrieval Pipeline (Vector + BM25 + RRF)` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `Streamlit Dashboard & SQLite Storage` to `Multi-Source Job Scraper`, `Candidate Profile & On-Demand Tailoring`, `Unified LLM Client`, `Job Normalization & Skill Extraction`, `Cross-Encoder Reranking & MMR`, `Email Digest & Notifications`, `Information Retrieval Evaluation Suite`, `Hybrid Retrieval & Scoring Engine`, `Vector Embeddings & BM25 Indexer`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `init_db()` connect `Streamlit Dashboard & SQLite Storage` to `Multi-Source Job Scraper`, `Candidate Profile & On-Demand Tailoring`, `Unified LLM Client`, `Job Normalization & Skill Extraction`, `Cross-Encoder Reranking & MMR`, `Email Digest & Notifications`, `Information Retrieval Evaluation Suite`, `Hybrid Retrieval & Scoring Engine`, `Vector Embeddings & BM25 Indexer`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `load_config()` connect `Email Digest & Notifications` to `Multi-Source Job Scraper`, `Candidate Profile & On-Demand Tailoring`, `Unified LLM Client`, `Job Normalization & Skill Extraction`, `Cross-Encoder Reranking & MMR`, `Hybrid Retrieval & Scoring Engine`, `Streamlit Dashboard & SQLite Storage`, `Vector Embeddings & BM25 Indexer`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **What connects `Graphify Knowledge Graph Rule`, `LaTeX Character Escaping Function`, `LaTeX Section Injection Mapping` to the rest of the system?**
  _14 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Resume Tailoring & LaTeX Compilation` be split into smaller, more focused modules?**
  _Cohesion score 0.09538461538461539 - nodes in this community are weakly interconnected._
- **Should `Candidate Profile & On-Demand Tailoring` be split into smaller, more focused modules?**
  _Cohesion score 0.13043478260869565 - nodes in this community are weakly interconnected._
- **Should `Unified LLM Client` be split into smaller, more focused modules?**
  _Cohesion score 0.1380952380952381 - nodes in this community are weakly interconnected._