"""
llm_client.py — Unified LLM abstraction layer (Ollama local & Google Gemini cloud).
"""

import json
import os
import re
import time
import requests
from config import load_config


def get_provider(config: dict) -> str:
    """Determine which LLM provider to use."""
    gemini_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
    return "gemini" if gemini_key else "ollama"


def query_llm(prompt: str, config: dict, temperature: float = 0.1,
              max_tokens: int = 1024, json_mode: bool = False) -> str | None:
    """Send a prompt to the configured LLM provider and return raw text response."""
    provider = get_provider(config)
    if provider == "gemini":
        return _query_gemini(prompt, config, temperature, max_tokens, json_mode)
    return _query_ollama(prompt, config, temperature, max_tokens, json_mode)


def parse_json_from_llm(text: str) -> dict | None:
    """Centralized extraction and parsing of JSON objects from LLM responses."""
    if not text:
        return None
    match = re.search(r"(\{.*\})", text.strip(), re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1), strict=False)
    except json.JSONDecodeError:
        return None


def _query_ollama(prompt: str, config: dict, temperature: float,
                  max_tokens: int, json_mode: bool) -> str | None:
    """Query local Ollama instance."""
    host = config.get("ollama", {}).get("host", "http://localhost:11434")
    model = config.get("ollama", {}).get("model", "llama3.2:3b")
    url = f"{host}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.ConnectionError:
        print("    [!] Ollama not reachable at localhost. Is it running?")
        gemini_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
        if gemini_key:
            print("    [*] Falling back to Google Gemini API...")
            return _query_gemini(prompt, config, temperature, max_tokens, json_mode)
        return None
    except Exception as e:
        print(f"    [!] Ollama API call failed: {e}")
        return None


def _query_gemini(prompt: str, config: dict, temperature: float,
                  max_tokens: int, json_mode: bool) -> str | None:
    """Query Google Gemini API with standard exponential backoff."""
    api_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
    if not api_key:
        print("    [!] GEMINI_API_KEY not set. Cannot use Gemini provider.")
        return None

    model = config.get("gemini", {}).get("model", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    backoff = 3
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                print(f"    [!] Gemini 429 rate limit. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
            return None
        except Exception as e:
            if attempt == 3:
                print(f"    [!] Gemini API call failed: {e}")
            time.sleep(backoff)
            backoff *= 2

    return None
