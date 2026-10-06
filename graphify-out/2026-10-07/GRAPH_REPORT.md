# Graph Report - job-discovery-assistant  (2026-10-07)

## Corpus Check
- 20 files · ~28,319 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 250 nodes · 508 edges · 10 communities (9 shown, 1 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 9 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `910b425f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Sourav Ray Master Candidate Profile
- scraper.py
- tailor.py
- run_pipeline.py
- normalizer.py
- get_connection
- Core Engineering Stages
- scorer.py
- retriever.py
- Graphify Knowledge Graph Rule

## God Nodes (most connected - your core abstractions)
1. `get_connection()` - 28 edges
2. `init_db()` - 23 edges
3. `load_config()` - 19 edges
4. `retrieve_jobs()` - 19 edges
5. `rerank_jobs()` - 12 edges
6. `normalize_job()` - 12 edges
7. `run_batch_tailoring()` - 12 edges
8. `run_pipeline()` - 11 edges
9. `normalize_job_record()` - 10 edges
10. `score_jobs()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `score_jobs()` --calls--> `load_config()`  [EXTRACTED]
  scorer.py → config.py
- `main()` --calls--> `load_config()`  [EXTRACTED]
  scraper.py → config.py
- `main()` --calls--> `load_config()`  [EXTRACTED]
  tailor.py → config.py
- `run_batch_tailoring()` --calls--> `load_config()`  [EXTRACTED]
  tailor.py → config.py
- `rerank_jobs()` --calls--> `load_candidate_profile()`  [EXTRACTED]
  reranker.py → config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Sourav Ray Enterprise Portfolio Projects** — sourav_ray_updated_profile_snowflake_cost_optimization_agent, sourav_ray_updated_profile_ai_network_incident_orchestrator, sourav_ray_updated_profile_customer_360_data_mesh, sourav_ray_updated_profile_genai_schema_validator [EXTRACTED 1.00]
- **Retrieval-First Job Discovery Architecture Pipeline** — readme_job_discovery_assistant_system, readme_hybrid_retrieval_pipeline, readme_cross_encoder_reranking, readme_blended_scoring [EXTRACTED 1.00]

## Communities (10 total, 1 thin omitted)

### Community 0 - "Sourav Ray Master Candidate Profile"
Cohesion: 0.10
Nodes (22): LaTeX Character Escaping Function, LaTeX Resume Generator Skill, Resume Positioning Personas Taxonomy, LaTeX Section Injection Mapping, Tectonic Resume Compilation Workflow, Job Discovery Scheduled Action Job, Daily Job Discovery & Auto-Tailoring CI/CD Workflow, Blended Composite Scoring Model (+14 more)

### Community 1 - "scraper.py"
Cohesion: 0.09
Nodes (41): load_ats_mapping(), Load company ATS mapping from company_ats_mapping.toml., compute_job_fingerprint(), Generate SHA-256 fingerprint from normalized (company, title, location) to…, fetch_ashby(), fetch_greenhouse(), fetch_greenhouse_description(), fetch_lever() (+33 more)

### Community 2 - "tailor.py"
Cohesion: 0.11
Nodes (29): load_candidate_profile(), Load candidate profile from Sourav_Ray_Updated_Profile.yaml., build_resume_context(), clean_date(), compile_pdf_resume(), escape_latex(), main(), now_iso() (+21 more)

### Community 3 - "run_pipeline.py"
Cohesion: 0.13
Nodes (23): auto_populate_config(), load_config(), config.py — Centralized configuration and YAML candidate profile loader using…, Load configuration from config.toml., Auto-populate config with boards from company_ats_mapping.toml., now_iso(), email_notifier.py — Send daily job digest and attached tailored PDF resumes via…, send_email_digest() (+15 more)

### Community 4 - "normalizer.py"
Cohesion: 0.15
Nodes (18): build_search_text(), classify_domain(), classify_role_family(), determine_remote_type(), extract_experience(), extract_skills_from_text(), normalize_job_record(), now_iso() (+10 more)

### Community 5 - "get_connection"
Cohesion: 0.08
Nodes (38): Connection, get_connection(), init_db(), _migrate_db(), db.py — SQLite database initialization and connection management. Implements a…, Apply schema migrations to ensure all new columns exist on existing tables., Create the database and tables if they don't exist, and migrate columns., Return a connection to the SQLite database with WAL and foreign keys. (+30 more)

### Community 6 - "Core Engineering Stages"
Cohesion: 0.13
Nodes (14): Core Engineering Stages, Ethical Grounding & Anti-Fabrication Rules, Executive Summary, High-Level System Architecture, Job Discovery & Application Assistant — System Architecture & Engineering Guide, Single Source of Truth: Candidate Profile Engine, Stage 1: Ingestion & Deterministic Normalization, Stage 2: Incremental Indexing & Hybrid Retrieval (+6 more)

### Community 7 - "scorer.py"
Cohesion: 0.14
Nodes (19): get_provider(), parse_json_from_llm(), _query_gemini(), query_llm(), _query_ollama(), llm_client.py — Unified LLM abstraction layer (Ollama local & Google Gemini…, Determine which LLM provider to use., Send a prompt to the configured LLM provider and return raw text response. (+11 more)

### Community 8 - "retriever.py"
Cohesion: 0.10
Nodes (23): Tokenize and clean text for BM25 matching., tokenize_for_bm25(), check_hard_filters(), compute_domain_score(), compute_experience_score(), compute_role_score(), compute_skill_overlap(), now_iso() (+15 more)

## Knowledge Gaps
- **26 isolated node(s):** `Executive Summary`, `High-Level System Architecture`, `Stage 1: Ingestion & Deterministic Normalization`, `Stage 2: Incremental Indexing & Hybrid Retrieval`, `Stage 3: Cross-Encoder Reranking & MMR Diversification` (+21 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `get_connection` to `scraper.py`, `tailor.py`, `run_pipeline.py`, `normalizer.py`, `scorer.py`, `retriever.py`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `init_db()` connect `get_connection` to `scraper.py`, `tailor.py`, `run_pipeline.py`, `normalizer.py`, `scorer.py`, `retriever.py`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `load_config()` connect `run_pipeline.py` to `scraper.py`, `tailor.py`, `normalizer.py`, `get_connection`, `scorer.py`, `retriever.py`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **What connects `Executive Summary`, `High-Level System Architecture`, `Stage 1: Ingestion & Deterministic Normalization` to the rest of the system?**
  _26 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Sourav Ray Master Candidate Profile` be split into smaller, more focused modules?**
  _Cohesion score 0.09523809523809523 - nodes in this community are weakly interconnected._
- **Should `scraper.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09413067552602436 - nodes in this community are weakly interconnected._
- **Should `tailor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10804597701149425 - nodes in this community are weakly interconnected._