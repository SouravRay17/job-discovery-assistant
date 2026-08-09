"""
scraper.py — Fetch job listings from public APIs and store in jobs.db.

Supports three sources:
  - Greenhouse (public board API, no auth)
  - Lever (public postings API, no auth)
  - RemoteOK (public JSON API, no auth)

Usage:
    python scraper.py                  # Fetch from all sources
    python scraper.py --source greenhouse  # Fetch from one source only
"""

import html
import json
import os
import re
import sqlite3
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests
import yaml

from db import get_connection, init_db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

HEADERS = {
    "User-Agent": "JobDiscoveryAssistant/1.0 (local; +https://github.com)",
    "Accept": "application/json",
}

# How long to wait between individual API requests (seconds)
REQUEST_DELAY = 1.0


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities to produce plain text."""
    if not text:
        return ""
    # Unescape HTML entities first (e.g. &amp; → &, &lt; → <)
    text = html.unescape(text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Base Fetcher
# ---------------------------------------------------------------------------

class BaseFetcher(ABC):
    """Abstract base class for job fetchers."""

    source_name: str = "unknown"

    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Fetch jobs and return a list of normalised job dicts."""
        ...

    def _is_location_suitable(self, location: str) -> bool:
        """Check if the job location is suitable based on config target_locations."""
        target_locations = self.config.get("candidate", {}).get("target_locations", [])
        if not target_locations:
            return True  # If not specified, allow all

        if not location:
            # Fallback if no location is specified: allow if 'remote' is acceptable
            return any(loc.lower() == "remote" for loc in target_locations)

        loc_lower = location.lower()

        # 1. Direct match with target locations (excluding general "remote")
        for target in target_locations:
            target_clean = target.lower().strip()
            if target_clean == "remote":
                continue
            if re.search(r'\b' + re.escape(target_clean) + r'\b', loc_lower):
                return True

        # Also handle common variants of India locations (using word boundaries to avoid matching Indiana)
        india_cities = ["india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "noida", "gurgaon", "chennai"]
        for city in india_cities:
            if re.search(r'\b' + city + r'\b', loc_lower):
                return True

        # 2. If remote is allowed, check if the job is remote and doesn't restrict to outside India
        if any(loc.lower() == "remote" for loc in target_locations):
            is_remote = "remote" in loc_lower or "anywhere" in loc_lower or "worldwide" in loc_lower or "global" in loc_lower
            if is_remote:
                # Check for restrictions to other countries / regions
                has_foreign_restriction = False
                foreign_keywords = [
                    "us", "united states", "usa", "uk", "united kingdom", "canada", 
                    "europe", "germany", "france", "emea", "latam", "americas", "north america",
                    "poland", "polska", "london"
                ]
                for keyword in foreign_keywords:
                    pattern = r"\b" + keyword + r"\b"
                    if re.search(pattern, loc_lower):
                        has_foreign_restriction = True
                        break

                if has_foreign_restriction:
                    if "india" in loc_lower or "worldwide" in loc_lower or "global" in loc_lower:
                        return True
                    return False
                return True

        return False

    def _is_role_relevant(self, title: str) -> bool:
        """Strict title relevance filter matching Sourav Ray's Data & AI Engineer profile."""
        if not title:
            return False

        t_lower = title.lower()

        # Hard exclusions for non-tech / non-relevant domain titles
        exclude_terms = [
            "store design", "refrigeration", "compliance", "civil", "mechanical", "hr ", "recruiter",
            "payroll", "accounting", "accountant", "facilities", "legal", "nurse", "sales representative",
            "marketing manager", "real estate", "chef", "security guard", "store manager", "merchandiser"
        ]
        for exc in exclude_terms:
            if exc in t_lower:
                return False

        # Target role patterns matching Data Engineer / AI Engineer / Python / ML / Backend Software Engineering
        relevant_patterns = [
            r"\bdata\b.*\bengineer\b", r"\bdata\b.*\bengineering\b", r"\bdata\b.*\barchitect\b",
            r"\banalytics\b.*\bengineer\b", r"\betl\b", r"\bpyspark\b", r"\bsnowflake\b",
            r"\bai\b.*\bengineer\b", r"\bai\b.*\bspecialist\b", r"\bai\b.*\bdeveloper\b",
            r"\bmachine\b.*\blearning\b", r"\bml\b.*\bengineer\b", r"\bmlops\b", r"\bgenai\b", r"\bllm\b",
            r"\bpython\b", r"\bbackend\b", r"\bback\s*end\b", r"\bsoftware\b.*\bengineer\b",
            r"\bdata\b.*\bplatform\b", r"\bdata\b.*\bscience\b", r"\bdata\b.*\bscientist\b"
        ]

        return any(re.search(pat, t_lower) for pat in relevant_patterns)

    def _get_json(self, url: str, params: dict | None = None, timeout: int = 30) -> dict | list | None:
        """Make a GET request and return parsed JSON, or None on failure."""
        try:
            resp = self.session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"  [!] Request failed for {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"  [!] Invalid JSON from {url}: {e}")
            return None


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
    """Create a normalised job dict matching the jobs table schema."""
    return {
        "id": str(job_id),
        "source": source,
        "company": company or "Unknown",
        "title": title or "Untitled",
        "location": location or "",
        "remote": remote,
        "url": url or "",
        "description_raw": description_raw,
        "date_posted": date_posted,
        "date_fetched": now_iso(),
        "score": None,
        "reasoning": None,
        "missing_requirements": None,
        "matching_strengths": None,
        "tailored_summary": None,
        "cover_letter_draft": None,
        "status": "new",
    }


# ---------------------------------------------------------------------------
# Greenhouse Fetcher
# ---------------------------------------------------------------------------

class GreenhouseFetcher(BaseFetcher):
    """Fetch jobs from Greenhouse public board API.

    List endpoint returns metadata only (no description).
    Description is fetched lazily via the detail endpoint when needed
    (e.g. during scoring). We store description_raw = None initially.
    """

    source_name = "greenhouse"

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    def fetch(self) -> list[dict]:
        boards = self.config.get("greenhouse_boards", [])
        all_jobs = []

        for board in boards:
            print(f"  >> Greenhouse: fetching board '{board}'...")
            url = f"{self.BASE_URL}/{board}/jobs"
            data = self._get_json(url, timeout=60)

            if data is None:
                print(f"  [!] Skipping board '{board}' (request failed)")
                continue

            jobs_list = data.get("jobs", [])
            print(f"     Found {len(jobs_list)} listings")

            fetched = 0
            filtered = 0

            for job in jobs_list:
                location_name = ""
                loc = job.get("location")
                if isinstance(loc, dict):
                    location_name = loc.get("name", "")

                title = job.get("title", "")
                if not self._is_role_relevant(title):
                    filtered += 1
                    continue

                if not self._is_location_suitable(location_name):
                    filtered += 1
                    continue

                remote = self._is_remote(location_name)

                normalised = normalize_job(
                    source=f"greenhouse:{board}",
                    job_id=str(job.get("id", "")),
                    company=job.get("company_name", board),
                    title=job.get("title", ""),
                    location=location_name,
                    remote=remote,
                    url=job.get("absolute_url", ""),
                    description_raw=None,  # Lazy — fetched during scoring
                    date_posted=job.get("first_published") or job.get("updated_at"),
                )
                all_jobs.append(normalised)
                fetched += 1

            print(f"     Kept {fetched}, filtered {filtered} by location")

        return all_jobs

    @staticmethod
    def _is_remote(location: str) -> bool:
        """Heuristic: check if location text suggests remote work."""
        if not location:
            return False
        return bool(re.search(r"\bremote\b", location, re.IGNORECASE))

    @classmethod
    def fetch_description(cls, board: str, job_id: str) -> str | None:
        """Fetch the full job description from the detail endpoint.

        Called on-demand during scoring, not during the initial fetch.
        """
        url = f"{cls.BASE_URL}/{board}/jobs/{job_id}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            return strip_html(content) if content else None
        except Exception as e:
            print(f"  [!] Failed to fetch Greenhouse description for {board}/{job_id}: {e}")
            return None


# ---------------------------------------------------------------------------
# Lever Fetcher
# ---------------------------------------------------------------------------

class LeverFetcher(BaseFetcher):
    """Fetch jobs from Lever public postings API.

    Unlike Greenhouse, Lever includes the full description in the list response.
    """

    source_name = "lever"

    BASE_URL = "https://api.lever.co/v0/postings"

    def fetch(self) -> list[dict]:
        boards = self.config.get("lever_boards", [])
        all_jobs = []

        for company in boards:
            print(f"  >> Lever: fetching company '{company}'...")
            url = f"{self.BASE_URL}/{company}"
            data = self._get_json(url, params={"mode": "json"}, timeout=60)

            if data is None:
                print(f"  [!] Skipping company '{company}' (request failed or 404)")
                continue

            if not isinstance(data, list):
                print(f"  [!] Unexpected response format for '{company}'")
                continue

            print(f"     Found {len(data)} listings")
            fetched = 0
            filtered = 0

            for job in data:
                categories = job.get("categories", {})
                location = categories.get("location", "")

                title = job.get("text", "")
                if not self._is_role_relevant(title):
                    filtered += 1
                    continue

                if not self._is_location_suitable(location):
                    filtered += 1
                    continue

                commitment = categories.get("commitment", "")

                remote = self._is_remote(location, commitment)

                # Lever provides descriptionPlain directly
                description = job.get("descriptionPlain", "")

                # Also include the lists (requirements, responsibilities, etc.)
                lists = job.get("lists", [])
                for lst in lists:
                    list_title = lst.get("text", "")
                    list_content = lst.get("content", "")
                    if list_title or list_content:
                        description += f"\n\n{list_title}\n{strip_html(list_content)}"

                normalised = normalize_job(
                    source=f"lever:{company}",
                    job_id=job.get("id", ""),
                    company=company.replace("-", " ").title(),
                    title=job.get("text", ""),
                    location=location,
                    remote=remote,
                    url=job.get("hostedUrl", ""),
                    description_raw=description.strip() or None,
                    date_posted=self._epoch_to_iso(job.get("createdAt")),
                )
                all_jobs.append(normalised)
                fetched += 1

            print(f"     Kept {fetched}, filtered {filtered} by location")

        return all_jobs

    @staticmethod
    def _is_remote(location: str, commitment: str) -> bool:
        """Check if the job location or commitment suggests remote."""
        text = f"{location} {commitment}".lower()
        return "remote" in text

    @staticmethod
    def _epoch_to_iso(epoch_ms: int | None) -> str | None:
        """Convert Lever's epoch-milliseconds timestamp to ISO 8601."""
        if epoch_ms is None:
            return None
        try:
            dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
            return dt.isoformat()
        except (ValueError, OSError):
            return None


# ---------------------------------------------------------------------------
# RemoteOK Fetcher
# ---------------------------------------------------------------------------

class RemoteOKFetcher(BaseFetcher):
    """Fetch jobs from RemoteOK's public JSON API.

    RemoteOK returns a lot of noisy/spam listings, so we filter using
    the candidate's target role keywords and configured tags.
    """

    source_name = "remoteok"

    BASE_URL = "https://remoteok.com/api"

    def fetch(self) -> list[dict]:
        tags = self.config.get("remoteok", {}).get("tags", [])
        target_roles = self.config.get("candidate", {}).get("target_roles", [])
        role_keywords = self._build_role_keywords(target_roles)

        all_jobs = []
        seen_ids = set()  # Deduplicate across tag queries

        for tag in tags:
            print(f"  >> RemoteOK: fetching tag '{tag}'...")
            data = self._get_json(f"{self.BASE_URL}?tag={tag}", timeout=30)

            if data is None:
                print(f"  [!] Skipping tag '{tag}' (request failed)")
                continue

            if not isinstance(data, list):
                continue

            # First element is always the legal/meta notice, skip it
            jobs_list = [j for j in data if isinstance(j, dict) and j.get("id")]

            fetched = 0
            filtered = 0

            for job in jobs_list:
                job_id = str(job.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = job.get("position", "")
                if not self._is_role_relevant(title):
                    filtered += 1
                    continue

                description = strip_html(job.get("description", ""))
                company = job.get("company", "")

                # Filter: skip if title+description don't match any role keyword
                if role_keywords and not self._matches_roles(title, description, role_keywords):
                    filtered += 1
                    continue

                location = job.get("location", "Remote")

                # Filter: skip if location is not suitable
                if not self._is_location_suitable(location):
                    filtered += 1
                    continue

                normalised = normalize_job(
                    source="remoteok",
                    job_id=job_id,
                    company=company,
                    title=title,
                    location=location,
                    remote=True,  # All RemoteOK jobs are remote by definition
                    url=job.get("url") or job.get("apply_url", ""),
                    description_raw=description or None,
                    date_posted=job.get("date"),
                )
                all_jobs.append(normalised)
                fetched += 1

            print(f"     Found {len(jobs_list)} listings, kept {fetched}, filtered {filtered} (role/location)")

            # Be polite — wait between tag queries
            if tag != tags[-1]:
                time.sleep(REQUEST_DELAY)

        return all_jobs

    @staticmethod
    def _build_role_keywords(target_roles: list[str]) -> list[str]:
        """Break target roles into individual lowercase keywords for matching."""
        keywords = set()
        for role in target_roles:
            for word in role.lower().split():
                # Skip very common words that would match too broadly
                if word not in ("and", "or", "the", "a", "an", "of", "in", "for"):
                    keywords.add(word)
        return list(keywords)

    @staticmethod
    def _matches_roles(title: str, description: str, keywords: list[str]) -> bool:
        """Check if the job title or first 500 chars of description contain role keywords."""
        text = f"{title} {description[:500]}".lower()
        return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# Workday CXS Fetcher
# ---------------------------------------------------------------------------

class WorkdayFetcher(BaseFetcher):
    """Fetch jobs from Workday CXS (Candidate Experience Site) API.

    Each company has its own CXS endpoint that accepts POST requests
    with search parameters and returns JSON job listings.
    """

    source_name = "workday"

    WORKDAY_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    PAGE_SIZE = 20  # Workday's typical page size

    def fetch(self) -> list[dict]:
        mapping = self._load_mapping()
        workday_companies = [c for c in mapping if c.get("ats") == "workday"]

        if not workday_companies:
            print("  [!] No Workday companies configured in company_ats_mapping.yaml")
            return []

        target_roles = self.config.get("candidate", {}).get("target_roles", [])
        all_jobs = []

        for company_info in workday_companies:
            company_name = company_info["name"]
            cxs_url = company_info.get("workday_url", "")
            if not cxs_url:
                continue

            print(f"  >> Workday: fetching '{company_name}'...")

            for role_keyword in target_roles:
                jobs = self._fetch_company_jobs(company_name, cxs_url, role_keyword)
                all_jobs.extend(jobs)
                time.sleep(REQUEST_DELAY * 2)  # Extra polite for Workday

        return all_jobs

    def _fetch_company_jobs(self, company_name: str, cxs_url: str, search_text: str) -> list[dict]:
        """Fetch paginated jobs from a single Workday CXS endpoint."""
        jobs = []
        offset = 0
        total = None
        seen_ids = set()

        while True:
            payload = {
                "appliedFacets": {},
                "limit": self.PAGE_SIZE,
                "offset": offset,
                "searchText": search_text,
            }

            try:
                resp = self.session.post(
                    cxs_url, json=payload, headers=self.WORKDAY_HEADERS, timeout=30
                )
                if resp.status_code != 200:
                    if offset == 0:
                        print(f"     [!] HTTP {resp.status_code} for '{company_name}' — skipping")
                    break

                data = resp.json()
            except requests.RequestException as e:
                print(f"     [!] Request failed for '{company_name}': {e}")
                break
            except json.JSONDecodeError:
                print(f"     [!] Invalid JSON from '{company_name}'")
                break

            if total is None:
                total = data.get("total", 0)
                if total == 0:
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

                location = job.get("locationsText", "")

                title = job.get("title", "")
                if not self._is_role_relevant(title):
                    continue

                if not self._is_location_suitable(location):
                    continue

                # Construct the apply URL
                base_url = cxs_url.replace("/wday/cxs/", "/").replace("/jobs", "")
                apply_url = f"{base_url}{ext_path}" if ext_path else ""

                remote = bool(re.search(r"\bremote\b", location, re.IGNORECASE))

                normalised = normalize_job(
                    source=f"workday:{company_name.lower().replace(' ', '_')}",
                    job_id=job_id,
                    company=company_name,
                    title=job.get("title", ""),
                    location=location,
                    remote=remote,
                    url=apply_url,
                    description_raw=None,  # Workday list endpoint doesn't include descriptions
                    date_posted=job.get("postedOn") or now_iso(),
                )
                jobs.append(normalised)

            offset += self.PAGE_SIZE
            if offset >= total:
                break

            time.sleep(REQUEST_DELAY)

        if jobs:
            print(f"     '{company_name}' [{search_text}]: {len(jobs)} jobs kept (total: {total})")

        return jobs

    @staticmethod
    def _load_mapping() -> list[dict]:
        """Load company ATS mapping from company_ats_mapping.yaml."""
        mapping_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "company_ats_mapping.yaml"
        )
        if not os.path.exists(mapping_path):
            print("  [!] company_ats_mapping.yaml not found")
            return []
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("companies", [])

    @classmethod
    def fetch_description(cls, company_slug: str, job_id: str) -> str | None:
        """Fetch the full job description from a Workday detail endpoint.

        Called on-demand during scoring.
        """
        mapping = cls._load_mapping()
        for c in mapping:
            if c.get("ats") == "workday" and c["name"].lower().replace(" ", "_") == company_slug:
                cxs_url = c.get("workday_url", "")
                detail_url = cxs_url.replace("/jobs", f"/job/{job_id}")
                try:
                    resp = requests.get(
                        detail_url,
                        headers=cls.WORKDAY_HEADERS,
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        desc = data.get("jobPostingInfo", {}).get("jobDescription", "")
                        return strip_html(desc) if desc else None
                except Exception as e:
                    print(f"  [!] Failed to fetch Workday description: {e}")
                break
        return None


# ---------------------------------------------------------------------------
# Naukri Fetcher
# ---------------------------------------------------------------------------

class NaukriFetcher(BaseFetcher):
    """Fetch jobs from Naukri.com public search results.

    Scrapes the public search API endpoint that Naukri uses internally.
    Falls back to HTML parsing if needed.
    """

    source_name = "naukri"

    # Naukri's internal job search API (used by the website itself)
    SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

    def fetch(self) -> list[dict]:
        naukri_config = self.config.get("naukri", {})
        keywords = naukri_config.get("keywords", [])
        location = naukri_config.get("location", "India")
        experience = naukri_config.get("experience", "3")

        if not keywords:
            target_roles = self.config.get("candidate", {}).get("target_roles", [])
            keywords = target_roles if target_roles else ["data engineer"]

        all_jobs = []
        seen_ids = set()

        for keyword in keywords:
            print(f"  >> Naukri: searching '{keyword}' in {location}...")
            jobs = self._search_naukri(keyword, location, experience, seen_ids)
            all_jobs.extend(jobs)
            time.sleep(REQUEST_DELAY * 3)  # Be extra polite to Naukri

        return all_jobs

    def _search_naukri(self, keyword: str, location: str, experience: str, seen_ids: set) -> list[dict]:
        """Search Naukri's internal API for job listings."""
        jobs = []

        # Naukri's internal API headers matching Chrome requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "appid": "109",
            "systemid": "Naukri",
            "clientid": "d341872b-4560-449a-a82f-2d4e5f2cf2e6",
            "gid": "LOCATION",
            "Referer": "https://www.naukri.com/",
        }

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
            resp = self.session.get(self.SEARCH_URL, params=params, headers=headers, timeout=30)

            if resp.status_code != 200:
                print(f"     [!] Naukri API returned HTTP {resp.status_code}")
                return jobs

            data = resp.json()
            job_list = data.get("jobDetails", [])

            if not job_list:
                print(f"     No results from Naukri for '{keyword}'")
                return jobs

            print(f"     Found {len(job_list)} listings")

            for job in job_list:
                job_id = str(job.get("jobId", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = job.get("title", "")
                if not self._is_role_relevant(title):
                    continue

                company = job.get("companyName", "")
                job_location = job.get("placeholders", [{}])[0].get("value", "") if job.get("placeholders") else ""

                # Skip if we can't determine location
                if not self._is_location_suitable(job_location or "India"):
                    continue

                remote = bool(re.search(r"\bremote\b", (job_location or ""), re.IGNORECASE))
                description = job.get("jobDescription", "")
                apply_url = f"https://www.naukri.com{job.get('jdURL', '')}" if job.get("jdURL") else ""

                normalised = normalize_job(
                    source="naukri",
                    job_id=job_id,
                    company=company,
                    title=title,
                    location=job_location or "India",
                    remote=remote,
                    url=apply_url,
                    description_raw=strip_html(description) if description else None,
                    date_posted=job.get("createdDate"),
                )
                jobs.append(normalised)

            print(f"     Kept {len(jobs)} jobs")

        except requests.RequestException as e:
            print(f"     [!] Naukri request failed: {e}")
        except json.JSONDecodeError:
            print(f"     [!] Failed to parse Naukri JSON response")
        except Exception as e:
            print(f"     [!] Naukri scraping error: {e}")

        return jobs


# ---------------------------------------------------------------------------
# LinkedIn Public Job Search Fetcher
# ---------------------------------------------------------------------------

class LinkedInFetcher(BaseFetcher):
    """Fetch jobs from LinkedIn's public job search.

    Uses LinkedIn's public job search page which does not require login.
    Very conservative rate limiting to avoid blocks.
    """

    source_name = "linkedin"

    SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def fetch(self) -> list[dict]:
        linkedin_config = self.config.get("linkedin", {})
        keywords = linkedin_config.get("keywords", [])
        location = linkedin_config.get("location", "India")

        if not keywords:
            target_roles = self.config.get("candidate", {}).get("target_roles", [])
            keywords = target_roles if target_roles else ["data engineer"]

        all_jobs = []
        seen_ids = set()

        for keyword in keywords:
            print(f"  >> LinkedIn: searching '{keyword}' in {location}...")
            jobs = self._search_linkedin(keyword, location, seen_ids)
            all_jobs.extend(jobs)
            time.sleep(REQUEST_DELAY * 5)  # Very conservative for LinkedIn

        return all_jobs

    def _search_linkedin(self, keyword: str, location: str, seen_ids: set) -> list[dict]:
        """Search LinkedIn's public job search API."""
        jobs = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Sec-Fetch-Mode": "navigate",
        }

        params = {
            "keywords": keyword,
            "location": location,
            "f_TPR": "r86400",  # Last 24 hours
            "start": "0",
            "count": "25",
        }

        try:
            resp = self.session.get(
                self.SEARCH_URL, params=params, headers=headers, timeout=30
            )

            if resp.status_code != 200:
                print(f"     [!] LinkedIn returned HTTP {resp.status_code}")
                return jobs

            # LinkedIn returns HTML fragments — parse with regex
            html_content = resp.text

            # Extract job cards using regex patterns
            job_cards = re.findall(
                r'<div class="base-card.*?data-entity-urn="urn:li:jobPosting:(\d+)".*?'
                r'<span class="sr-only">(.*?)</span>.*?'
                r'<h4[^>]*class="base-search-card__subtitle[^"]*"[^>]*>\s*'
                r'<a[^>]*>(.*?)</a>.*?'
                r'<span class="job-search-card__location">(.*?)</span>',
                html_content, re.DOTALL
            )

            if not job_cards:
                print(f"     No LinkedIn results for '{keyword}' (may need to retry later)")
                return jobs

            print(f"     Found {len(job_cards)} listings")

            for job_id, title, company, job_location in job_cards:
                job_id = job_id.strip()
                title = title.strip()
                company = company.strip()
                job_location = job_location.strip()

                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                if not self._is_role_relevant(title):
                    continue

                if not self._is_location_suitable(job_location or "India"):
                    continue

                remote = bool(re.search(r"\bremote\b", job_location, re.IGNORECASE))
                apply_url = f"https://www.linkedin.com/jobs/view/{job_id}/"

                normalised = normalize_job(
                    source="linkedin",
                    job_id=job_id,
                    company=company,
                    title=title,
                    location=job_location,
                    remote=remote,
                    url=apply_url,
                    description_raw=None,  # Would need separate request per job
                    date_posted=now_iso(),
                )
                jobs.append(normalised)

            print(f"     Kept {len(jobs)} jobs")

        except requests.RequestException as e:
            print(f"     [!] LinkedIn request failed: {e}")
        except Exception as e:
            print(f"     [!] LinkedIn scraping error: {e}")

        return jobs


# ---------------------------------------------------------------------------
# Mapping Loader
# ---------------------------------------------------------------------------

def load_ats_mapping() -> list[dict]:
    """Load company_ats_mapping.yaml and return the companies list."""
    mapping_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "company_ats_mapping.yaml"
    )
    if not os.path.exists(mapping_path):
        return []
    with open(mapping_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def auto_populate_config(config: dict) -> dict:
    """Auto-populate config with boards from company_ats_mapping.yaml.

    Merges any boards specified in mapping into the config, so the
    Greenhouse and Lever fetchers automatically pick them up.
    """
    mapping = load_ats_mapping()

    # Collect Greenhouse boards
    gh_boards = set(config.get("greenhouse_boards", []))
    for c in mapping:
        if c.get("ats") == "greenhouse" and c.get("greenhouse_board"):
            gh_boards.add(c["greenhouse_board"])
    config["greenhouse_boards"] = sorted(gh_boards)

    # Collect Lever boards
    lever_boards = set(config.get("lever_boards", []))
    for c in mapping:
        if c.get("ats") == "lever" and c.get("lever_slug"):
            lever_boards.add(c["lever_slug"])
    config["lever_boards"] = sorted(lever_boards)

    return config


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------

def upsert_jobs(jobs: list[dict]) -> tuple[int, int]:
    """Insert jobs into the database, skipping duplicates.

    Returns (inserted_count, skipped_count).
    """
    if not jobs:
        return 0, 0

    conn = get_connection()
    inserted = 0
    skipped = 0

    try:
        for job in jobs:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (id, source, company, title, location, remote, url,
                        description_raw, date_posted, date_fetched,
                        score, reasoning, missing_requirements, matching_strengths,
                        tailored_summary, cover_letter_draft, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job["id"],
                        job["source"],
                        job["company"],
                        job["title"],
                        job["location"],
                        job["remote"],
                        job["url"],
                        job["description_raw"],
                        job["date_posted"],
                        job["date_fetched"],
                        job["score"],
                        job["reasoning"],
                        job["missing_requirements"],
                        job["matching_strengths"],
                        job["tailored_summary"],
                        job["cover_letter_draft"],
                        job["status"],
                    ),
                )
                if conn.total_changes > inserted + skipped:
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

FETCHER_MAP = {
    "greenhouse": GreenhouseFetcher,
    "lever": LeverFetcher,
    "remoteok": RemoteOKFetcher,
    "workday": WorkdayFetcher,
    "naukri": NaukriFetcher,
    "linkedin": LinkedInFetcher,
}


def run_all_fetchers(config: dict, sources: list[str] | None = None) -> dict:
    """Run all (or selected) fetchers and upsert results.

    Returns a summary dict with per-source counts.
    """
    if sources is None:
        sources = list(FETCHER_MAP.keys())

    summary = {}

    for source_name in sources:
        fetcher_cls = FETCHER_MAP.get(source_name)
        if fetcher_cls is None:
            print(f"[!] Unknown source: {source_name}")
            continue

        print(f"\n{'-'*50}")
        print(f"--> Fetching from: {source_name}")
        print(f"{'-'*50}")

        fetcher = fetcher_cls(config)
        try:
            jobs = fetcher.fetch()
        except Exception as e:
            print(f"  [ERR] Fetcher '{source_name}' crashed: {e}")
            summary[source_name] = {"fetched": 0, "inserted": 0, "skipped": 0, "error": str(e)}
            continue

        print(f"\n  [DB] Upserting {len(jobs)} jobs into database...")
        inserted, skipped = upsert_jobs(jobs)
        print(f"  [OK] Inserted: {inserted}, Skipped (duplicates): {skipped}")

        summary[source_name] = {
            "fetched": len(jobs),
            "inserted": inserted,
            "skipped": skipped,
        }

    return summary


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch jobs from public APIs")
    parser.add_argument(
        "--source",
        type=str,
        choices=list(FETCHER_MAP.keys()),
        help="Fetch from a specific source only (default: all)",
    )
    args = parser.parse_args()

    config = load_config()

    # Auto-populate config from company_ats_mapping.yaml
    config = auto_populate_config(config)

    # Ensure DB is initialised
    init_db()

    print(f"\n{'='*60}")
    print(f"Job Scraper -- Job Discovery Assistant")
    print(f"{'='*60}")
    print(f"Started at: {now_iso()}")

    # Show source counts
    mapping = load_ats_mapping()
    ats_counts = {}
    for c in mapping:
        ats_type = c.get("ats", "custom")
        ats_counts[ats_type] = ats_counts.get(ats_type, 0) + 1
    print(f"Company mapping: {ats_counts}")
    print(f"Greenhouse boards: {len(config.get('greenhouse_boards', []))}")
    print(f"Lever boards: {len(config.get('lever_boards', []))}")

    sources = [args.source] if args.source else None
    summary = run_all_fetchers(config, sources)

    # Print summary
    print(f"\n{'='*60}")
    print("Fetch Summary")
    print(f"{'='*60}")

    total_fetched = 0
    total_inserted = 0

    for source, counts in summary.items():
        fetched = counts.get("fetched", 0)
        inserted = counts.get("inserted", 0)
        error = counts.get("error")
        total_fetched += fetched
        total_inserted += inserted

        status = f"[OK] {fetched} fetched, {inserted} new" if not error else f"[ERR] {error}"
        print(f"  {source:15s} -> {status}")

    print(f"\n  {'Total':15s} -> {total_fetched} fetched, {total_inserted} new")

    # Show DB total
    try:
        conn = get_connection()
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
        print(f"\n  [#] Database now contains {total} jobs total")
    except Exception:
        pass

    print()


if __name__ == "__main__":
    main()

