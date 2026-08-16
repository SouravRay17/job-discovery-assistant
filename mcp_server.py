"""
mcp_server.py — Model Context Protocol (MCP) server for Job Discovery Assistant.

Exposes tools to scrape, score, tailor, and notify jobs via stdio transport.
"""

import os
import json
import sqlite3
import yaml
from fastmcp import FastMCP
from db import get_connection

mcp = FastMCP(name="Job Discovery Assistant")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
CV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cv_profile.json")

def check_env() -> str | None:
    """Check if config.yaml and cv_profile.json are present."""
    if not os.path.exists(CONFIG_PATH):
        return f"Configuration file not found at {CONFIG_PATH}."
    if not os.path.exists(CV_PATH):
        return f"CV profile file not found at {CV_PATH}. Please run: python cv_parser.py --cv <path_to_docx>"
    return None

@mcp.tool()
def fetch_new_jobs(sources: str = "") -> str:
    """Scrape new job postings from configured public boards/APIs.
    
    Args:
        sources: Comma-separated list of sources (e.g. 'greenhouse,lever,remoteok,workday,naukri,linkedin'). If empty, fetches all configured sources.
    """
    err = check_env()
    if err:
        return f"Error: {err}"
    
    from scraper import load_config, run_all_fetchers, auto_populate_config
    try:
        config = load_config()
        config = auto_populate_config(config)
        
        src_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
        res = run_all_fetchers(config, src_list)
        return json.dumps(res, indent=2)
    except Exception as e:
        return f"Error during fetching: {e}"

@mcp.tool()
def score_unscored_jobs() -> str:
    """Evaluate and score all unscored jobs in the database against the candidate's resume."""
    err = check_env()
    if err:
        return f"Error: {err}"
    
    from scorer import score_jobs
    try:
        score_jobs()
        return "Job fit scoring complete. Checked all unscored listings."
    except Exception as e:
        return f"Error during scoring: {e}"

@mcp.tool()
def tailor_specific_job(source: str, job_id: str) -> str:
    """Generate a tailored resume professional summary, cover letter draft, and LaTeX PDF for a specific job match.
    
    Args:
        source: The job source (e.g. 'greenhouse:stripe', 'remoteok').
        job_id: The job ID in the database.
    """
    err = check_env()
    if err:
        return f"Error: {err}"
    
    from tailor import tailor_job, compile_pdf_resume
    from scraper import load_config
    
    try:
        config = load_config()
        with open(CV_PATH, "r", encoding="utf-8") as f:
            cv_profile = json.load(f)
            
        success = tailor_job(source, job_id, config, cv_profile)
        if success:
            pdf_path = compile_pdf_resume(source, job_id)
            return f"Success! Tailored summary & cover letter created. LaTeX resume compiled at: {pdf_path}"
        else:
            return "Failed to tailor job (Ollama/Gemini client returned failure)."
    except Exception as e:
        return f"Error during tailoring: {e}"

@mcp.tool()
def get_top_matches(limit: int = 10, min_score: int = 70) -> str:
    """Retrieve top matched jobs from the database that haven't been rejected.
    
    Args:
        limit: Max number of jobs to return.
        min_score: Minimum match score threshold (0-100).
    """
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT source, id, company, title, score, location, url, status, 
                   notified_email, notified_whatsapp, tailored_summary 
            FROM jobs 
            WHERE score >= ? 
              AND status != 'rejected'
            ORDER BY score DESC 
            LIMIT ?
        """, (min_score, limit))
        rows = [dict(r) for r in cursor.fetchall()]
        return json.dumps(rows, indent=2)
    except Exception as e:
        return f"Error fetching matches: {e}"
    finally:
        conn.close()

@mcp.tool()
def send_digest_notifications() -> str:
    """Send daily job digest updates via Email and WhatsApp for newly qualified matching jobs."""
    err = check_env()
    if err:
        return f"Error: {err}"
    
    from email_notifier import send_email_digest
    from whatsapp_notifier import notify_top_jobs_whatsapp
    
    email_res = "Not run"
    wa_res = "Not run"
    
    try:
        send_email_digest(top_n=10)
        email_res = "Success"
    except Exception as e:
        email_res = f"Failed: {e}"
        
    try:
        notify_top_jobs_whatsapp()
        wa_res = "Success"
    except Exception as e:
        wa_res = f"Failed: {e}"
        
    return f"Notification dispatch run complete:\n- Email Digest: {email_res}\n- WhatsApp Notification: {wa_res}"

@mcp.tool()
def run_full_pipeline() -> str:
    """Execute the entire pipeline in sequence (Fetch -> Score -> Tailor -> Notify)."""
    err = check_env()
    if err:
        return f"Error: {err}"
    
    from run_pipeline import run_pipeline
    try:
        run_pipeline()
        return "Job discovery pipeline run completed successfully."
    except Exception as e:
        return f"Error during pipeline execution: {e}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
