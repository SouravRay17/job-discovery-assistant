"""
cv_parser.py — Parse a DOCX CV into structured JSON profile using LLM.

Extracts raw text from the DOCX file, then structures it into standardized JSON.

Usage:
    python cv_parser.py
    python cv_parser.py --cv /path/to/resume.docx
"""

import argparse
import json
import os
import re
import sys
import time
from docx import Document
from config import load_config, CV_PATH


def extract_text(file_path: str) -> str:
    """Extract text from a DOCX file using python-docx."""
    if not file_path.lower().endswith((".docx", ".doc")):
        raise ValueError(f"Unsupported file format: {file_path}. Use DOCX.")
    doc = Document(file_path)
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


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


def _extract_json(text: str) -> str:
    """Extract JSON object from response using native regex search."""
    match = re.search(r"(\{.*\})", text.strip(), re.DOTALL)
    return match.group(1) if match else text.strip()


def parse_cv_with_llm(raw_text: str, config: dict, max_retries: int = 3) -> dict | None:
    """Send CV text to LLM for structured extraction with retry logic."""
    from llm_client import query_llm

    prompt = EXTRACTION_PROMPT + raw_text
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Attempt {attempt}/{max_retries}: Structuring CV with LLM...")
            response_text = query_llm(prompt=prompt, config=config, temperature=0.1, max_tokens=4096, json_mode=True)
            if not response_text:
                continue

            json_str = _extract_json(response_text)
            parsed = json.loads(json_str)

            if parsed.get("name"):
                print(f"  Success on attempt {attempt}.")
                return parsed
        except Exception as e:
            print(f"  Attempt {attempt} failed: {e}")

        if attempt < max_retries:
            time.sleep(2 ** attempt)

    return None


def parse_cv(cv_path: str, config: dict) -> dict:
    """Parse a CV file into a structured JSON profile."""
    print(f"\n{'='*60}\nCV Parser — Job Discovery Assistant\n{'='*60}")
    print(f"\n[1/2] Extracting text from: {cv_path}")
    if not os.path.exists(cv_path):
        print(f"  ERROR: File not found: {cv_path}")
        sys.exit(1)

    raw_text = extract_text(cv_path)
    word_count = len(raw_text.split())
    print(f"  Extracted {word_count} words, {len(raw_text)} characters.")

    print(f"\n[2/2] Structuring CV data via LLM...")
    profile = parse_cv_with_llm(raw_text, config)

    if profile is None:
        if os.path.exists(CV_PATH):
            print(f"  [!] LLM parsing failed. Reusing existing profile from {CV_PATH}")
            with open(CV_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        print("  [ERR] Failed to structure CV and no cached cv_profile.json found.")
        sys.exit(1)

    with open(CV_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"  Done! Profile saved to {CV_PATH} with {len(profile.get('skills', []))} skills, "
          f"{len(profile.get('work_history', []))} work entries.")
    return profile


def main():
    parser = argparse.ArgumentParser(description="Parse CV into structured JSON")
    parser.add_argument("--cv", type=str, help="Path to CV file (overrides config.toml)")
    args = parser.parse_args()

    config = load_config()
    cv_path = args.cv or config.get("cv", {}).get("file_path")
    if not cv_path:
        print("ERROR: No CV path provided. Set it in config.toml or use --cv flag.")
        sys.exit(1)

    cv_path = os.path.normpath(cv_path)
    profile = parse_cv(cv_path, config)

    print(f"\n{'='*60}\nCV Profile Summary:\n{'='*60}")
    print(f"  Name:       {profile.get('name', 'N/A')}")
    print(f"  Email:      {profile.get('contact', {}).get('email', 'N/A')}")
    print(f"  Experience: {profile.get('years_of_experience', 'N/A')} years")
    print(f"  Skills:     {len(profile.get('skills', []))} found")
    print(f"  Work:       {len(profile.get('work_history', []))} entries")
    print(f"  Education:  {len(profile.get('education', []))} entries")
    print(f"  Certs:      {len(profile.get('certifications', []))} entries")
    print(f"\nFull profile saved to: {CV_PATH}")


if __name__ == "__main__":
    main()
