"""
db.py — SQLite database initialization and connection management.

Implements a two-table relational architecture:
  1. `jobs`: Relational storage of raw & normalized job information.
  2. `candidate_job_scores`: Candidate-specific hybrid retrieval, reranking,
     and AI evaluation scores.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

SCHEMA_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT,
    title TEXT,
    location TEXT,
    remote BOOLEAN,
    url TEXT,
    description_raw TEXT,
    search_text TEXT,
    required_skills TEXT,
    preferred_skills TEXT,
    role_family TEXT,
    domain TEXT,
    experience_min REAL,
    experience_max REAL,
    education TEXT,
    certifications TEXT,
    employment_type TEXT,
    remote_type TEXT,
    salary TEXT,
    date_posted TEXT,
    date_fetched TEXT,
    normalized_at TEXT,
    indexed_at TEXT,
    PRIMARY KEY (source, id)
);
"""

SCHEMA_SCORES = """
CREATE TABLE IF NOT EXISTS candidate_job_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT DEFAULT 'default',
    candidate_version TEXT DEFAULT '2.0',
    source TEXT NOT NULL,
    job_id TEXT NOT NULL,
    semantic_score REAL,
    bm25_score REAL,
    required_skill_score REAL,
    preferred_skill_score REAL,
    role_score REAL,
    experience_score REAL,
    hybrid_retrieval_score REAL,
    reranker_score REAL,
    mmr_selected BOOLEAN DEFAULT 0,
    llm_score INTEGER,
    final_composite_score REAL,
    recommendation TEXT,
    match_reason TEXT,
    strengths TEXT,
    skill_gaps TEXT,
    critical_gap BOOLEAN DEFAULT 0,
    user_rating INTEGER,
    user_feedback TEXT,
    labeled_at TEXT,
    tailored_summary TEXT,
    cover_letter_draft TEXT,
    status TEXT DEFAULT 'retrieved',
    notified_email INTEGER DEFAULT 0,
    notified_whatsapp INTEGER DEFAULT 0,
    retrieved_at TEXT,
    reranked_at TEXT,
    ai_reviewed_at TEXT,
    tailored_at TEXT,
    notified_at TEXT,
    FOREIGN KEY (source, job_id) REFERENCES jobs(source, id) ON DELETE CASCADE,
    UNIQUE(candidate_id, source, job_id)
);
"""


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database with WAL and foreign keys."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Apply schema migrations to ensure all new columns exist on existing tables."""
    # Check jobs table columns
    cursor = conn.execute("PRAGMA table_info(jobs);")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    expected_job_cols = {
        "search_text": "TEXT",
        "required_skills": "TEXT",
        "preferred_skills": "TEXT",
        "role_family": "TEXT",
        "domain": "TEXT",
        "experience_min": "REAL",
        "experience_max": "REAL",
        "education": "TEXT",
        "certifications": "TEXT",
        "employment_type": "TEXT",
        "remote_type": "TEXT",
        "salary": "TEXT",
        "normalized_at": "TEXT",
        "indexed_at": "TEXT",
    }

    for col, col_type in expected_job_cols.items():
        if col not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type};")
            except sqlite3.OperationalError:
                pass

    # Check candidate_job_scores table columns
    cursor_scores = conn.execute("PRAGMA table_info(candidate_job_scores);")
    existing_score_cols = {row["name"] for row in cursor_scores.fetchall()}

    expected_score_cols = {
        "final_composite_score": "REAL",
        "user_rating": "INTEGER",
        "user_feedback": "TEXT",
        "labeled_at": "TEXT",
    }

    for col, col_type in expected_score_cols.items():
        if col not in existing_score_cols:
            try:
                conn.execute(f"ALTER TABLE candidate_job_scores ADD COLUMN {col} {col_type};")
            except sqlite3.OperationalError:
                pass


def init_db() -> None:
    """Create the database and tables if they don't exist, and migrate columns."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_JOBS)
        conn.executescript(SCHEMA_SCORES)
        _migrate_db(conn)
        conn.commit()
        print(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()

