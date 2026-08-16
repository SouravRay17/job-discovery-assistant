"""
db.py — SQLite database initialization and connection management.

Provides a single-file database (jobs.db) for storing job listings,
scores, and tailored application materials.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT NOT NULL,
    source TEXT NOT NULL,
    company TEXT,
    title TEXT,
    location TEXT,
    remote BOOLEAN,
    url TEXT,
    description_raw TEXT,
    date_posted TEXT,
    date_fetched TEXT,
    score INTEGER,
    reasoning TEXT,
    missing_requirements TEXT,
    matching_strengths TEXT,
    tailored_summary TEXT,
    cover_letter_draft TEXT,
    status TEXT DEFAULT 'new',
    notified_email INTEGER DEFAULT 0,
    notified_whatsapp INTEGER DEFAULT 0,
    PRIMARY KEY (source, id)
);
"""


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Create the database and tables if they don't exist."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        
        # Migrations to add new columns dynamically for existing databases
        import sqlite3
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN notified_email INTEGER DEFAULT 0;")
            conn.commit()
            print("Migration: Added notified_email column to jobs table.")
        except sqlite3.OperationalError:
            pass  # Already exists

        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN notified_whatsapp INTEGER DEFAULT 0;")
            conn.commit()
            print("Migration: Added notified_whatsapp column to jobs table.")
        except sqlite3.OperationalError:
            pass  # Already exists

        print(f"Database initialized and migrated at {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
