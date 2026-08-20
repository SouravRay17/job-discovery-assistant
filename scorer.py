"""
scorer.py — Score jobs against CV using LLM (Ollama local or Google Gemini cloud).

Evaluates fit based on: required experience, skills, seniority, and location.
Automatically fetches lazy Greenhouse/Workday descriptions on demand.
"""

import json
import os
import re
import sys
import time

from config import load_config, CONFIG_PATH, CV_PATH, DB_PATH
from db import get_connection
from scraper import fetch_greenhouse_description, fetch_workday_description

SYSTEM_PROMPT = """You are a job-fit evaluator. You will be given a candidate profile and a job description.
Score fit from 0-100 based on: required years of experience, required skills overlap,
title/seniority match, and location/remote compatibility.
Do not invent or assume candidate qualifications not present in the profile.
Return ONLY valid JSON in this exact format, no other text:
{
  "score": <int 0-100>,
  "reasoning": "<2-3 sentence explanation>",
  "missing_requirements": ["<requirement not met>", ...],
  "matching_strengths": ["<matching qualification>", ...]
}"""

MAX_RETRIES = 3
RETRY_DELAY = 2.0


def validate_environment() -> tuple[dict, dict]:
    """Verify that all configuration files exist."""
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Configuration file not found at {CONFIG_PATH}")
        sys.exit(1)

    if not os.path.exists(CV_PATH):
        print(f"Error: CV profile file not found at {CV_PATH}. Run cv_parser.py first.")
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"Error: Jobs database not found at {DB_PATH}. Run scraper.py first.")
        sys.exit(1)

    config = load_config()

    try:
        with open(CV_PATH, "r", encoding="utf-8") as f:
            cv_profile = json.load(f)
    except Exception as e:
        print(f"Error: Failed to parse cv_profile.json: {e}")
        sys.exit(1)

    return config, cv_profile


def query_scoring_llm(prompt: str, config: dict) -> dict | None:
    """Send evaluation prompt to LLM (Ollama or Gemini), parse and validate JSON."""
    from llm_client import query_llm

    response_text = query_llm(
        prompt=prompt,
        config=config,
        temperature=0.1,
        max_tokens=1024,
        json_mode=False
    )
    if not response_text:
        return None
    return parse_and_validate_json(response_text)


def parse_and_validate_json(text: str) -> dict | None:
    """Extract JSON object from response and validate keys."""
    match = re.search(r"(\{.*\})", text.strip(), re.DOTALL)
    if not match:
        print("    [!] No JSON structure found in response.")
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"    [!] Failed to parse JSON: {e}")
        return None

    required_keys = ["score", "reasoning", "missing_requirements", "matching_strengths"]
    for key in required_keys:
        if key not in data:
            print(f"    [!] Missing key '{key}' in JSON response.")
            return None

    try:
        score = int(data["score"])
        if not (0 <= score <= 100):
            return None
        data["score"] = score
    except (ValueError, TypeError):
        return None

    if not isinstance(data["missing_requirements"], list):
        data["missing_requirements"] = [str(data["missing_requirements"])]
    if not isinstance(data["matching_strengths"], list):
        data["matching_strengths"] = [str(data["matching_strengths"])]

    return data


def score_jobs():
    config, cv_profile = validate_environment()
    score_threshold = config.get("scoring", {}).get("threshold", 60)

    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT source, id, title, company, location, remote, description_raw "
            "FROM jobs WHERE score IS NULL"
        )
        unscored_jobs = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not unscored_jobs:
        print("No unscored jobs found. Database is up to date!")
        return

    print(f"\n{'='*60}\nJob Scorer -- Job Discovery Assistant\n{'='*60}")
    print(f"Found {len(unscored_jobs)} unscored jobs. Evaluating...")

    scored_count = 0
    failed_count = 0
    consecutive_failures = 0

    for i, job in enumerate(unscored_jobs, 1):
        job_source = job["source"]
        job_id = job["id"]
        title = job["title"]
        company = job["company"]
        location = job["location"]
        remote = job["remote"]
        description = job["description_raw"]

        print(f"\n[{i}/{len(unscored_jobs)}] {title} at {company} ({location})")

        if not description:
            if job_source.startswith("greenhouse:"):
                board = job_source.split(":", 1)[1]
                description = fetch_greenhouse_description(board, job_id)
            elif job_source.startswith("workday:"):
                company_slug = job_source.split(":", 1)[1]
                description = fetch_workday_description(company_slug, job_id)

            if description:
                conn = get_connection()
                try:
                    conn.execute(
                        "UPDATE jobs SET description_raw = ? WHERE source = ? AND id = ?",
                        (description, job_source, job_id)
                    )
                    conn.commit()
                finally:
                    conn.close()
                print("     Saved description to database.")
            else:
                description = f"Role: {title} at {company} located in {location}. Remote preference: {remote}."

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

        eval_result = None
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                time.sleep(RETRY_DELAY)
            eval_result = query_scoring_llm(prompt, config)
            if eval_result is not None:
                break

        if eval_result is None:
            print("  [ERR] Failed to evaluate job after retries.")
            failed_count += 1
            consecutive_failures += 1
            if consecutive_failures >= 5:
                print("\n[CRITICAL] Too many consecutive LLM failures (5). Exiting.")
                sys.exit(1)
            continue

        consecutive_failures = 0
        score = eval_result["score"]
        reasoning = eval_result["reasoning"]
        missing_reqs = json.dumps(eval_result["missing_requirements"])
        strengths = json.dumps(eval_result["matching_strengths"])
        status = "to_review" if score >= score_threshold else "rejected"

        conn = get_connection()
        try:
            conn.execute(
                """UPDATE jobs
                   SET score = ?, reasoning = ?, missing_requirements = ?, 
                       matching_strengths = ?, status = ?
                   WHERE source = ? AND id = ?""",
                (score, reasoning, missing_reqs, strengths, status, job_source, job_id)
            )
            conn.commit()
        finally:
            conn.close()

        print(f"  -> Score: {score}/100 ({status})")
        print(f"  -> Reason: {reasoning}")
        scored_count += 1

    print(f"\n{'='*60}\nScoring Run Completed: Scored {scored_count}, Failed {failed_count}\n{'='*60}\n")


if __name__ == "__main__":
    score_jobs()
