"""
cv_parser.py — Parse a CV (PDF or DOCX) into structured JSON.

Extracts raw text from the CV file, then uses Ollama to structure it
into a standardized JSON profile. Falls back to basic regex extraction
if Ollama is unavailable.

Usage:
    python cv_parser.py
    python cv_parser.py --cv /path/to/resume.pdf
"""

import json
import os
import re
import sys
import argparse
import time

import yaml
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cv_profile.json")


def load_config() -> dict:
    """Load configuration from config.yaml."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Text Extraction
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using pdfplumber."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from a DOCX file using python-docx."""
    from docx import Document

    doc = Document(file_path)
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def extract_text(file_path: str) -> str:
    """Extract text from a CV file (PDF or DOCX)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}. Use PDF or DOCX.")


# ---------------------------------------------------------------------------
# Ollama Structuring
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a CV/resume parser. Extract ONLY the information present in the text below.
Do NOT embellish, infer, or fabricate any details. If a field is not present, use null or an empty array.

Return ONLY valid JSON (no markdown fences, no extra text) with exactly these fields:
{
  "name": "<full name>",
  "contact": {
    "email": "<email or null>",
    "phone": "<phone or null>",
    "linkedin": "<linkedin url or null>",
    "github": "<github url or null>",
    "portfolio": "<portfolio url or null>"
  },
  "years_of_experience": <number or null>,
  "skills": ["<skill1>", "<skill2>", ...],
  "work_history": [
    {
      "company": "<company name>",
      "title": "<job title>",
      "start_date": "<start date>",
      "end_date": "<end date or Present>",
      "bullets": ["<responsibility/achievement>", ...]
    }
  ],
  "education": [
    {
      "institution": "<school name>",
      "degree": "<degree>",
      "field": "<field of study>",
      "year": "<graduation year or null>"
    }
  ],
  "certifications": ["<cert1>", "<cert2>", ...]
}

Here is the CV text:
"""


def call_ollama(raw_text: str, config: dict, max_retries: int = 3) -> dict | None:
    """Send CV text to Ollama for structured extraction with retry logic."""
    host = config["ollama"]["host"]
    model = config["ollama"]["model"]
    url = f"{host}/api/generate"

    payload = {
        "model": model,
        "prompt": EXTRACTION_PROMPT + raw_text,
        "stream": False,
        "options": {
            "temperature": 0.1,  # Low temperature for factual extraction
            "num_predict": 4096,
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Attempt {attempt}/{max_retries}: Calling Ollama ({model})...")
            resp = requests.post(url, json=payload, timeout=300)
            resp.raise_for_status()

            response_text = resp.json().get("response", "")

            # Try to extract JSON from the response (handle markdown fences)
            json_str = _extract_json(response_text)
            parsed = json.loads(json_str)

            # Basic validation: must have at least a name
            if not parsed.get("name"):
                print(f"  Attempt {attempt}: Response missing 'name' field, retrying...")
                continue

            print(f"  Success on attempt {attempt}.")
            return parsed

        except requests.ConnectionError:
            print(f"  Cannot connect to Ollama at {host}. Is it running?")
            return None
        except requests.Timeout:
            print(f"  Attempt {attempt}: Ollama request timed out.")
        except json.JSONDecodeError as e:
            print(f"  Attempt {attempt}: Malformed JSON response: {e}")
        except Exception as e:
            print(f"  Attempt {attempt}: Unexpected error: {e}")

        if attempt < max_retries:
            wait = 2 ** attempt
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)

    print("  All Ollama attempts failed.")
    return None


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might include markdown fences."""
    # Remove markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        text = re.sub(r"^```\w*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)

    # Find the first { and last } to extract JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text


# ---------------------------------------------------------------------------
# Fallback Regex Extraction
# ---------------------------------------------------------------------------

def fallback_extract(raw_text: str, config: dict) -> dict:
    """Basic regex-based extraction when Ollama is unavailable."""
    print("  Using fallback regex extraction...")

    profile = {
        "name": None,
        "contact": {
            "email": None,
            "phone": None,
            "linkedin": None,
            "github": None,
            "portfolio": None,
        },
        "years_of_experience": config.get("candidate", {}).get("years_of_experience"),
        "skills": [],
        "work_history": [],
        "education": [],
        "certifications": [],
    }

    lines = raw_text.strip().split("\n")

    # Name: usually the first non-empty line
    for line in lines:
        line = line.strip()
        if line and not re.search(r"[@.|/]", line):  # Skip emails/urls
            profile["name"] = line
            break

    # Email
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw_text)
    if email_match:
        profile["contact"]["email"] = email_match.group()

    # Phone
    phone_match = re.search(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text
    )
    if phone_match:
        profile["contact"]["phone"] = phone_match.group()

    # LinkedIn
    linkedin_match = re.search(r"linkedin\.com/in/[\w-]+", raw_text, re.IGNORECASE)
    if linkedin_match:
        profile["contact"]["linkedin"] = "https://" + linkedin_match.group()

    # GitHub
    github_match = re.search(r"github\.com/[\w-]+", raw_text, re.IGNORECASE)
    if github_match:
        profile["contact"]["github"] = "https://" + github_match.group()

    # Skills: look for a skills section and extract comma/pipe-separated items
    skills_section = re.search(
        r"(?:skills|technologies|tech\s*stack)[:\s]*\n?(.*?)(?:\n\n|\n[A-Z])",
        raw_text,
        re.IGNORECASE | re.DOTALL,
    )
    if skills_section:
        skills_text = skills_section.group(1)
        # Split on commas, pipes, bullets, or newlines
        skills = re.split(r"[,|•·\n]+", skills_text)
        profile["skills"] = [s.strip() for s in skills if s.strip() and len(s.strip()) < 50]

    return profile


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_cv(cv_path: str, config: dict) -> dict:
    """Parse a CV file into a structured JSON profile."""
    print(f"\n{'='*60}")
    print(f"CV Parser — Job Discovery Assistant")
    print(f"{'='*60}")

    # Step 1: Extract raw text
    print(f"\n[1/3] Extracting text from: {cv_path}")
    if not os.path.exists(cv_path):
        print(f"  ERROR: File not found: {cv_path}")
        sys.exit(1)

    raw_text = extract_text(cv_path)
    word_count = len(raw_text.split())
    print(f"  Extracted {word_count} words, {len(raw_text)} characters.")

    if word_count < 20:
        print("  WARNING: Very little text extracted. Check if the PDF is image-based.")

    # Step 2: Structure with Ollama (or fallback)
    print(f"\n[2/3] Structuring CV data...")
    profile = call_ollama(raw_text, config)

    if profile is None:
        profile = fallback_extract(raw_text, config)

    # Step 3: Save output
    print(f"\n[3/3] Saving to: {OUTPUT_PATH}")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"  Done! Profile saved with {len(profile.get('skills', []))} skills, "
          f"{len(profile.get('work_history', []))} work entries.")

    return profile


def main():
    parser = argparse.ArgumentParser(description="Parse CV into structured JSON")
    parser.add_argument("--cv", type=str, help="Path to CV file (overrides config.yaml)")
    args = parser.parse_args()

    config = load_config()

    cv_path = args.cv or config.get("cv", {}).get("file_path")
    if not cv_path:
        print("ERROR: No CV path provided. Set it in config.yaml or use --cv flag.")
        sys.exit(1)

    # Normalize path
    cv_path = os.path.normpath(cv_path)

    profile = parse_cv(cv_path, config)

    # Print summary
    print(f"\n{'='*60}")
    print("CV Profile Summary:")
    print(f"{'='*60}")
    print(f"  Name:       {profile.get('name', 'N/A')}")
    print(f"  Email:      {profile.get('contact', {}).get('email', 'N/A')}")
    print(f"  Experience: {profile.get('years_of_experience', 'N/A')} years")
    print(f"  Skills:     {len(profile.get('skills', []))} found")
    print(f"  Work:       {len(profile.get('work_history', []))} entries")
    print(f"  Education:  {len(profile.get('education', []))} entries")
    print(f"  Certs:      {len(profile.get('certifications', []))} entries")
    print(f"\nFull profile saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
