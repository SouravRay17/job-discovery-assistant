"""
config.py — Centralized configuration and YAML candidate profile loader using stdlib tomllib & pyyaml.
"""

import os
import tomllib
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.toml")
ATS_MAPPING_PATH = os.path.join(BASE_DIR, "company_ats_mapping.toml")
CV_PATH = os.path.join(BASE_DIR, "Sourav_Ray_Updated_Profile.yaml")
DB_PATH = os.path.join(BASE_DIR, "jobs.db")


def load_config() -> dict:
    """Load configuration from config.toml."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def load_candidate_profile() -> dict:
    """Load candidate profile from Sourav_Ray_Updated_Profile.yaml."""
    if not os.path.exists(CV_PATH):
        raise FileNotFoundError(f"Candidate profile not found at {CV_PATH}")

    with open(CV_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return {}

    # Ensure standardized contact and experience fields
    if "contact" not in data and "personal_info" in data:
        p = data["personal_info"]
        data["contact"] = {
            "name": p.get("name", "Sourav Ray"),
            "location": p.get("location", "Bengaluru, India"),
            "phone": p.get("phone", "+91-7872567781"),
            "email": p.get("email", "sroy.dgp2014@gmail.com"),
            "linkedin": p.get("linkedin", "linkedin.com/in/souravray17"),
            "github": p.get("github", "github.com/SouravRay17")
        }
        data["experience_years"] = p.get("years_experience", 3)

    return data


def load_ats_mapping() -> list[dict]:
    """Load company ATS mapping from company_ats_mapping.toml."""
    if os.path.exists(ATS_MAPPING_PATH):
        with open(ATS_MAPPING_PATH, "rb") as f:
            data = tomllib.load(f)
            return data.get("companies", [])
    return []


def auto_populate_config(config: dict) -> dict:
    """Auto-populate config with boards from company_ats_mapping.toml."""
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
