"""
scraper.py — Fetch job listings from public APIs and store in jobs.db.

Supported sources:
  - Greenhouse (public board API)
  - Lever (public postings API)
  - RemoteOK (public JSON API)
  - Workday (CXS API endpoints)
  - Naukri (public search API)
  - LinkedIn (public search API)

Usage:
    python scraper.py                  # Fetch from all sources
    python scraper.py --source greenhouse  # Fetch from one source only
"""

import html
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
import requests

from config import load_config, load_ats_mapping, auto_populate_config
from db import get_connection, init_db

HEADERS = {
    "User-Agent": "JobDiscoveryAssistant/1.0 (local; +https://github.com)",
    "Accept": "application/json",
}

REQUEST_DELAY = 1.0


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities to produce plain text."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def is_location_suitable(location: str, target_locations: list[str]) -> bool:
    """Check if the job location is suitable based on target_locations."""
    if not target_locations:
        return True

    if not location:
        return any(loc.lower() == "remote" for loc in target_locations)

    loc_lower = location.lower()
    for target in target_locations:
        target_clean = target.lower().strip()
        if target_clean == "remote":
            continue
        if re.search(r'\b' + re.escape(target_clean) + r'\b', loc_lower):
            return True

    india_cities = ["india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "noida", "gurgaon", "chennai"]
    for city in india_cities:
        if re.search(r'\b' + city + r'\b', loc_lower):
            return True

    if any(loc.lower() == "remote" for loc in target_locations):
        is_remote = any(k in loc_lower for k in ("remote", "anywhere", "worldwide", "global"))
        if is_remote:
            foreign_keywords = [
                "us", "united states", "usa", "uk", "united kingdom", "canada", 
                "europe", "germany", "france", "emea", "latam", "americas", "north america",
                "poland", "polska", "london"
            ]
            has_foreign = any(re.search(r'\b' + kw + r'\b', loc_lower) for kw in foreign_keywords)
            if has_foreign:
                return any(k in loc_lower for k in ("india", "worldwide", "global"))
            return True

    return False


def is_role_relevant(title: str) -> bool:
    """Filter role titles matching Data & AI Engineer profile."""
    if not title:
        return False
    t_lower = title.lower()

    exclude_terms = [
        "store design", "refrigeration", "compliance", "civil", "mechanical", "hr ", "recruiter",
        "payroll", "accounting", "accountant", "facilities", "legal", "nurse", "sales representative",
        "marketing manager", "real estate", "chef", "security guard", "store manager", "merchandiser"
    ]
    if any(exc in t_lower for exc in exclude_terms):
        return False

    relevant_patterns = [
        r"\bdata\b.*\bengineer\b", r"\bdata\b.*\bengineering\b", r"\bdata\b.*\barchitect\b",
        r"\banalytics\b.*\bengineer\b", r"\betl\b", r"\bpyspark\b", r"\bsnowflake\b",
        r"\bai\b.*\bengineer\b", r"\bai\b.*\bspecialist\b", r"\bai\b.*\bdeveloper\b",
        r"\bmachine\b.*\blearning\b", r"\bml\b.*\bengineer\b", r"\bmlops\b", r"\bgenai\b", r"\bllm\b",
        r"\bpython\b", r"\bbackend\b", r"\bback\s*end\b", r"\bsoftware\b.*\bengineer\b",
        r"\bdata\b.*\bplatform\b", r"\bdata\b.*\bscience\b", r"\bdata\b.*\bscientist\b"
    ]
    return any(re.search(pat, t_lower) for pat in relevant_patterns)


def normalize_job(
    source: str,
    job_id: str,
    company: str,
    title: str,
    location: str,
    remote: bool,
    url: str,
    description_raw: str | None,
    date_posted: str | None,
) -> dict:
    """Create a normalised raw job dict matching the jobs table schema."""
    return {
        "id": str(job_id),
        "source": source,
        "company": (company or "Unknown").strip(),
        "title": (title or "Untitled").strip(),
        "location": (location or "").strip(),
        "remote": remote,
        "url": (url or "").strip(),
        "description_raw": description_raw,
        "date_posted": date_posted,
        "date_fetched": now_iso(),
    }


# ---------------------------------------------------------------------------
# Fetch Functions
# ---------------------------------------------------------------------------

def fetch_greenhouse(config: dict) -> list[dict]:
    """Fetch jobs from Greenhouse public board API."""
    boards = config.get("greenhouse_boards", [])
    target_locations = config.get("candidate", {}).get("target_locations", [])
    all_jobs = []

    for board in boards:
        print(f"  >> Greenhouse: fetching board '{board}'...")
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60)
            if resp.status_code != 200:
                print(f"  [!] Skipping board '{board}' (status {resp.status_code})")
                continue
            data = resp.json()
        except Exception as e:
            print(f"  [!] Request failed for '{board}': {e}")
            continue

        jobs_list = data.get("jobs", [])
        print(f"     Found {len(jobs_list)} listings")

        fetched, filtered = 0, 0
        for job in jobs_list:
            loc = job.get("location")
            location_name = loc.get("name", "") if isinstance(loc, dict) else ""
            title = job.get("title", "")

            if not is_role_relevant(title) or not is_location_suitable(location_name, target_locations):
                filtered += 1
                continue

            remote = bool(re.search(r"\bremote\b", location_name, re.IGNORECASE))
            all_jobs.append(normalize_job(
                source=f"greenhouse:{board}",
                job_id=str(job.get("id", "")),
                company=job.get("company_name", board),
                title=title,
                location=location_name,
                remote=remote,
                url=job.get("absolute_url", ""),
                description_raw=None,
                date_posted=job.get("first_published") or job.get("updated_at"),
            ))
            fetched += 1

        print(f"     Kept {fetched}, filtered {filtered}")

    return all_jobs


def fetch_greenhouse_description(board: str, job_id: str) -> str | None:
    """Fetch full job description from Greenhouse detail endpoint on demand."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        content = resp.json().get("content", "")
        return strip_html(content) if content else None
    except Exception as e:
        print(f"  [!] Failed to fetch Greenhouse description for {board}/{job_id}: {e}")
        return None


def fetch_lever(config: dict) -> list[dict]:
    """Fetch jobs from Lever public postings API."""
    boards = config.get("lever_boards", [])
    target_locations = config.get("candidate", {}).get("target_locations", [])
    all_jobs = []

    for company in boards:
        print(f"  >> Lever: fetching company '{company}'...")
        url = f"https://api.lever.co/v0/postings/{company}"
        try:
            resp = requests.get(url, params={"mode": "json"}, headers=HEADERS, timeout=60)
            if resp.status_code != 200:
                print(f"  [!] Skipping company '{company}' (status {resp.status_code})")
                continue
            data = resp.json()
        except Exception as e:
            print(f"  [!] Request failed for '{company}': {e}")
            continue

        if not isinstance(data, list):
            continue

        print(f"     Found {len(data)} listings")
        fetched, filtered = 0, 0

        for job in data:
            categories = job.get("categories", {})
            location = categories.get("location", "")
            title = job.get("text", "")

            if not is_role_relevant(title) or not is_location_suitable(location, target_locations):
                filtered += 1
                continue

            commitment = categories.get("commitment", "")
            remote = "remote" in f"{location} {commitment}".lower()

            description = job.get("descriptionPlain", "")
            for lst in job.get("lists", []):
                lt, lc = lst.get("text", ""), lst.get("content", "")
                if lt or lc:
                    description += f"\n\n{lt}\n{strip_html(lc)}"

            epoch_ms = job.get("createdAt")
            date_posted = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat() if epoch_ms else None

            all_jobs.append(normalize_job(
                source=f"lever:{company}",
                job_id=job.get("id", ""),
                company=company.replace("-", " ").title(),
                title=title,
                location=location,
                remote=remote,
                url=job.get("hostedUrl", ""),
                description_raw=description.strip() or None,
                date_posted=date_posted,
            ))
            fetched += 1

        print(f"     Kept {fetched}, filtered {filtered}")

    return all_jobs


def fetch_remoteok(config: dict) -> list[dict]:
    """Fetch jobs from RemoteOK public JSON API."""
    tags = config.get("remoteok", {}).get("tags", [])
    target_locations = config.get("candidate", {}).get("target_locations", [])
    target_roles = config.get("candidate", {}).get("target_roles", [])
    role_keywords = [w.lower() for r in target_roles for w in r.split() if w.lower() not in ("and", "or", "the", "a", "an", "of", "in", "for")]

    all_jobs = []
    seen_ids = set()

    for tag in tags:
        print(f"  >> RemoteOK: fetching tag '{tag}'...")
        try:
            resp = requests.get(f"https://remoteok.com/api?tag={tag}", headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception as e:
            print(f"  [!] RemoteOK request error: {e}")
            continue

        if not isinstance(data, list):
            continue

        jobs_list = [j for j in data if isinstance(j, dict) and j.get("id")]
        fetched, filtered = 0, 0

        for job in jobs_list:
            job_id = str(job.get("id", ""))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = job.get("position", "")
            if not is_role_relevant(title):
                filtered += 1
                continue

            description = strip_html(job.get("description", ""))
            company = job.get("company", "")
            text = f"{title} {description[:500]}".lower()

            if role_keywords and not any(kw in text for kw in role_keywords):
                filtered += 1
                continue

            location = job.get("location", "Remote")
            if not is_location_suitable(location, target_locations):
                filtered += 1
                continue

            all_jobs.append(normalize_job(
                source="remoteok",
                job_id=job_id,
                company=company,
                title=title,
                location=location,
                remote=True,
                url=job.get("url") or job.get("apply_url", ""),
                description_raw=description or None,
                date_posted=job.get("date"),
            ))
            fetched += 1

        print(f"     Found {len(jobs_list)}, kept {fetched}, filtered {filtered}")
        time.sleep(REQUEST_DELAY)

    return all_jobs


def fetch_workday(config: dict) -> list[dict]:
    """Fetch jobs from Workday CXS APIs."""
    mapping = load_ats_mapping()
    workday_companies = [c for c in mapping if c.get("ats") == "workday"]
    if not workday_companies:
        return []

    target_roles = config.get("candidate", {}).get("target_roles", [])
    target_locations = config.get("candidate", {}).get("target_locations", [])
    all_jobs = []

    workday_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    for company_info in workday_companies:
        company_name = company_info["name"]
        cxs_url = company_info.get("workday_url", "")
        if not cxs_url:
            continue

        print(f"  >> Workday: fetching '{company_name}'...")
        seen_ids = set()

        for search_text in target_roles:
            offset = 0
            while True:
                payload = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search_text}
                try:
                    resp = requests.post(cxs_url, json=payload, headers=workday_headers, timeout=30)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                except Exception:
                    break

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for job in postings:
                    ext_path = job.get("externalPath", "")
                    job_id = ext_path.split("/")[-1] if ext_path else str(hash(job.get("title", "")))
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    title = job.get("title", "")
                    location = job.get("locationsText", "")

                    if not is_role_relevant(title) or not is_location_suitable(location, target_locations):
                        continue

                    base_url = cxs_url.replace("/wday/cxs/", "/").replace("/jobs", "")
                    apply_url = f"{base_url}{ext_path}" if ext_path else ""
                    remote = bool(re.search(r"\bremote\b", location, re.IGNORECASE))

                    all_jobs.append(normalize_job(
                        source=f"workday:{company_name.lower().replace(' ', '_')}",
                        job_id=job_id,
                        company=company_name,
                        title=title,
                        location=location,
                        remote=remote,
                        url=apply_url,
                        description_raw=None,
                        date_posted=job.get("postedOn") or now_iso(),
                    ))

                offset += 20
                if offset >= data.get("total", 0):
                    break
                time.sleep(REQUEST_DELAY)

    return all_jobs


def fetch_workday_description(company_slug: str, job_id: str) -> str | None:
    """Fetch full job description from Workday detail endpoint on demand."""
    mapping = load_ats_mapping()
    workday_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    for c in mapping:
        if c.get("ats") == "workday" and c["name"].lower().replace(" ", "_") == company_slug:
            cxs_url = c.get("workday_url", "")
            detail_url = cxs_url.replace("/jobs", f"/job/{job_id}")
            try:
                resp = requests.get(detail_url, headers=workday_headers, timeout=30)
                if resp.status_code == 200:
                    desc = resp.json().get("jobPostingInfo", {}).get("jobDescription", "")
                    return strip_html(desc) if desc else None
            except Exception as e:
                print(f"  [!] Failed to fetch Workday description: {e}")
            break
    return None


def fetch_naukri(config: dict) -> list[dict]:
    """Fetch jobs from Naukri public search API."""
    naukri_config = config.get("naukri", {})
    keywords = naukri_config.get("keywords") or config.get("candidate", {}).get("target_roles", ["data engineer"])
    location = naukri_config.get("location", "India")
    experience = naukri_config.get("experience", "3")
    target_locations = config.get("candidate", {}).get("target_locations", [])

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "appid": "109",
        "systemid": "Naukri",
        "clientid": "d341872b-4560-449a-a82f-2d4e5f2cf2e6",
        "gid": "LOCATION",
        "Referer": "https://www.naukri.com/",
    }

    all_jobs = []
    seen_ids = set()

    for keyword in keywords:
        print(f"  >> Naukri: searching '{keyword}' in {location}...")
        params = {
            "noOfResults": "50",
            "urlType": "search_by_key_loc",
            "searchType": "adv",
            "keyword": keyword,
            "location": location,
            "experience": experience,
            "pageNo": "1",
        }
        try:
            resp = requests.get("https://www.naukri.com/jobapi/v3/search", params=params, headers=headers, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception as e:
            print(f"  [!] Naukri request error: {e}")
            continue

        for job in data.get("jobDetails", []):
            job_id = str(job.get("jobId", ""))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = job.get("title", "")
            if not is_role_relevant(title):
                continue

            job_location = job.get("placeholders", [{}])[0].get("value", "") if job.get("placeholders") else ""
            if not is_location_suitable(job_location or "India", target_locations):
                continue

            remote = bool(re.search(r"\bremote\b", (job_location or ""), re.IGNORECASE))
            apply_url = f"https://www.naukri.com{job.get('jdURL', '')}" if job.get("jdURL") else ""

            all_jobs.append(normalize_job(
                source="naukri",
                job_id=job_id,
                company=job.get("companyName", ""),
                title=title,
                location=job_location or "India",
                remote=remote,
                url=apply_url,
                description_raw=strip_html(job.get("jobDescription", "")) or None,
                date_posted=job.get("createdDate"),
            ))

        time.sleep(REQUEST_DELAY * 2)

    return all_jobs


def fetch_linkedin(config: dict) -> list[dict]:
    """Fetch jobs from LinkedIn public job search."""
    linkedin_config = config.get("linkedin", {})
    keywords = linkedin_config.get("keywords") or config.get("candidate", {}).get("target_roles", ["data engineer"])
    location = linkedin_config.get("location", "India")
    target_locations = config.get("candidate", {}).get("target_locations", [])

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Sec-Fetch-Mode": "navigate",
    }

    all_jobs = []
    seen_ids = set()

    for keyword in keywords:
        print(f"  >> LinkedIn: searching '{keyword}' in {location}...")
        params = {
            "keywords": keyword,
            "location": location,
            "f_TPR": "r86400",
            "start": "0",
            "count": "25",
        }
        try:
            resp = requests.get(
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
                params=params, headers=headers, timeout=30
            )
            if resp.status_code != 200:
                continue
            html_content = resp.text
        except Exception as e:
            print(f"  [!] LinkedIn request error: {e}")
            continue

        job_cards = re.findall(
            r'<div class="base-card.*?data-entity-urn="urn:li:jobPosting:(\d+)".*?'
            r'<span class="sr-only">(.*?)</span>.*?'
            r'<h4[^>]*class="base-search-card__subtitle[^"]*"[^>]*>\s*'
            r'<a[^>]*>(.*?)</a>.*?'
            r'<span class="job-search-card__location">(.*?)</span>',
            html_content, re.DOTALL
        )

        for job_id, title, company, job_location in job_cards:
            job_id, title, company, job_location = job_id.strip(), title.strip(), company.strip(), job_location.strip()
            if job_id in seen_ids or not is_role_relevant(title) or not is_location_suitable(job_location or "India", target_locations):
                continue
            seen_ids.add(job_id)

            remote = bool(re.search(r"\bremote\b", job_location, re.IGNORECASE))
            all_jobs.append(normalize_job(
                source="linkedin",
                job_id=job_id,
                company=company,
                title=title,
                location=job_location,
                remote=remote,
                url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                description_raw=None,
                date_posted=now_iso(),
            ))

        time.sleep(REQUEST_DELAY * 3)

    return all_jobs


FETCHER_MAP = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "remoteok": fetch_remoteok,
    "workday": fetch_workday,
    "naukri": fetch_naukri,
    "linkedin": fetch_linkedin,
}


def upsert_jobs(jobs: list[dict]) -> tuple[int, int]:
    """Insert jobs into the database, skipping duplicates."""
    if not jobs:
        return 0, 0

    conn = get_connection()
    inserted, skipped = 0, 0
    try:
        for job in jobs:
            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (id, source, company, title, location, remote, url,
                        description_raw, date_posted, date_fetched)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job["id"], job["source"], job["company"], job["title"],
                        job["location"], job["remote"], job["url"], job["description_raw"],
                        job["date_posted"], job["date_fetched"]
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except sqlite3.Error as e:
                print(f"  [!] DB error for job {job.get('id')}: {e}")
                skipped += 1
        conn.commit()
    finally:
        conn.close()

    return inserted, skipped


def run_all_fetchers(config: dict, sources: list[str] | None = None) -> dict:
    """Run all (or selected) fetchers and upsert results."""
    if sources is None:
        sources = list(FETCHER_MAP.keys())

    summary = {}
    for source_name in sources:
        fetch_fn = FETCHER_MAP.get(source_name)
        if not fetch_fn:
            continue

        print(f"\n{'-'*50}\n--> Fetching from: {source_name}\n{'-'*50}")
        try:
            jobs = fetch_fn(config)
        except Exception as e:
            print(f"  [ERR] Fetcher '{source_name}' crashed: {e}")
            summary[source_name] = {"fetched": 0, "inserted": 0, "skipped": 0, "error": str(e)}
            continue

        print(f"\n  [DB] Upserting {len(jobs)} jobs into database...")
        inserted, skipped = upsert_jobs(jobs)
        print(f"  [OK] Inserted: {inserted}, Skipped (duplicates): {skipped}")
        summary[source_name] = {"fetched": len(jobs), "inserted": inserted, "skipped": skipped}

    return summary


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch jobs from public APIs")
    parser.add_argument("--source", type=str, choices=list(FETCHER_MAP.keys()), help="Fetch from specific source")
    args = parser.parse_args()

    config = load_config()
    config = auto_populate_config(config)
    init_db()

    print(f"\n{'='*60}\nJob Scraper -- Job Discovery Assistant\n{'='*60}")
    print(f"Started at: {now_iso()}")

    summary = run_all_fetchers(config, [args.source] if args.source else None)
    total_fetched = sum(c.get("fetched", 0) for c in summary.values())
    total_inserted = sum(c.get("inserted", 0) for c in summary.values())

    print(f"\n{'='*60}\nFetch Summary\n{'='*60}")
    for source, counts in summary.items():
        print(f"  {source:15s} -> {counts.get('fetched', 0)} fetched, {counts.get('inserted', 0)} new")
    print(f"\n  {'Total':15s} -> {total_fetched} fetched, {total_inserted} new\n")


if __name__ == "__main__":
    main()
