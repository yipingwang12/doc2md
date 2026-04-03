"""Ollama REST API wrapper for local LLM inference."""

from __future__ import annotations

import json
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)


class LlmError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1:8b",
                 timeout: int = 120, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def generate(self, prompt: str) -> str:
        """Send a prompt to Ollama and return the raw response text."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()["response"]
            except (requests.RequestException, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise LlmError(f"Ollama request failed after {self.max_retries} attempts: {e}")
                wait = 2 ** attempt
                logger.warning("Ollama attempt %d failed, retrying in %ds: %s", attempt + 1, wait, e)
                time.sleep(wait)

        raise LlmError("Unexpected retry exhaustion")

    def generate_json(self, prompt: str) -> dict | list:
        """Send a prompt and parse the response as JSON."""
        raw = self.generate(prompt)
        return _parse_json(raw)


def _parse_json(text: str) -> dict | list:
    """Parse JSON from LLM output, handling common malformations."""
    text = text.strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try fixing trailing commas
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LlmError(f"Failed to parse LLM JSON response: {e}\nRaw: {text[:500]}")
