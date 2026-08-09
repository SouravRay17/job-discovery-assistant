"""
llm_client.py — Unified LLM abstraction layer.

Supports:
  - Ollama (local, default for development)
  - Google Gemini API (cloud, for GitHub Actions / production)

Automatically selects the provider based on config.yaml or environment variables.
Falls back gracefully: tries Gemini first if API key is set, else Ollama.
"""

import json
import os
import re
import requests
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_provider(config: dict) -> str:
    """Determine which LLM provider to use.
    
    Priority:
      1. GEMINI_API_KEY env var set → 'gemini'
      2. config.yaml gemini.api_key set → 'gemini'
      3. Ollama reachable at localhost → 'ollama'
      4. Default → 'gemini' if key exists, else 'ollama'
    """
    gemini_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
    if gemini_key:
        return "gemini"
    return "ollama"


def query_llm(prompt: str, config: dict, temperature: float = 0.1,
              max_tokens: int = 1024, json_mode: bool = False) -> str | None:
    """Send a prompt to the configured LLM provider and return raw text response.
    
    Args:
        prompt: The full prompt string (including system instructions).
        config: Loaded config.yaml dict.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
        json_mode: If True, request JSON output format (supported by both providers).
    
    Returns:
        Raw text response string, or None on failure.
    """
    provider = get_provider(config)
    
    if provider == "gemini":
        return _query_gemini(prompt, config, temperature, max_tokens, json_mode)
    else:
        return _query_ollama(prompt, config, temperature, max_tokens, json_mode)


# ---------------------------------------------------------------------------
# Ollama (Local)
# ---------------------------------------------------------------------------

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
        # Try Gemini as fallback
        gemini_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
        if gemini_key:
            print("    [*] Falling back to Google Gemini API...")
            return _query_gemini(prompt, config, temperature, max_tokens, json_mode)
        return None
    except Exception as e:
        print(f"    [!] Ollama API call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Google Gemini API (Cloud)
# ---------------------------------------------------------------------------

def _query_gemini(prompt: str, config: dict, temperature: float,
                  max_tokens: int, json_mode: bool) -> str | None:
    """Query Google Gemini API (free tier).
    
    Uses the v1beta generateContent endpoint.
    Model: gemini-2.0-flash (free, fast, high quality).
    """
    api_key = os.getenv("GEMINI_API_KEY") or config.get("gemini", {}).get("api_key", "")
    if not api_key:
        print("    [!] GEMINI_API_KEY not set. Cannot use Gemini provider.")
        return None

    model = config.get("gemini", {}).get("model", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Build request payload
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
    }

    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        # Extract text from response
        candidates = data.get("candidates", [])
        if not candidates:
            print("    [!] Gemini returned no candidates.")
            # Check for prompt blocking
            block_reason = data.get("promptFeedback", {}).get("blockReason")
            if block_reason:
                print(f"    [!] Prompt blocked: {block_reason}")
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            print("    [!] Gemini returned empty content.")
            return None

        return parts[0].get("text", "")

    except requests.HTTPError as e:
        error_body = ""
        try:
            error_body = e.response.json().get("error", {}).get("message", "")
        except Exception:
            pass
        print(f"    [!] Gemini API error ({e.response.status_code}): {error_body or e}")
        return None
    except Exception as e:
        print(f"    [!] Gemini API call failed: {e}")
        return None
