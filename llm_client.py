"""
llm_client.py — Unified LLM abstraction layer.

Supports:
  - Ollama (local, default for development)
  - Google Gemini API (cloud, for GitHub Actions / production)

Automatically selects the provider based on config.toml or environment variables.
"""

import json
import os
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
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
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
    """Query Google Gemini API with automatic retry and backoff."""
    api_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
    if not api_key:
        print("    [!] GEMINI_API_KEY not set. Cannot use Gemini provider.")
        return None

    model = config.get("gemini", {}).get("model", "gemini-3.5-flash")
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

    import time
    max_api_retries = 5
    backoff_time = 10

    for attempt in range(1, max_api_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 429:
                print(f"    [!] Gemini rate limit (429). Retrying in {backoff_time}s...")
                time.sleep(backoff_time)
                backoff_time *= 2
                continue

            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None

            parts = candidates[0].get("content", {}).get("parts", [])
            return parts[0].get("text", "") if parts else None

        except requests.HTTPError as e:
            if e.response.status_code >= 500:
                time.sleep(backoff_time)
                backoff_time *= 2
                continue
            return None
        except Exception as e:
            print(f"    [!] Gemini API call failed: {e}")
            return None

    return None
