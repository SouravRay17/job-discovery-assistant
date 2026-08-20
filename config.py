"""
config.py — Centralized configuration loader for Job Discovery Assistant using stdlib tomllib.
"""

import os
import tomllib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.toml")
ATS_MAPPING_PATH = os.path.join(BASE_DIR, "company_ats_mapping.toml")
CV_PATH = os.path.join(BASE_DIR, "cv_profile.json")
DB_PATH = os.path.join(BASE_DIR, "jobs.db")


def load_config() -> dict:
    """Load configuration from config.toml."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


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
