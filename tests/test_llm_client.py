"""Tests for Ollama LLM client."""

import json

import pytest
import responses

from doc2md.analysis.llm_client import LlmError, OllamaClient, _parse_json


class TestParseJson:
    def test_plain_json(self):
        assert _parse_json('{"key": "value"}') == {"key": "value"}

    def test_json_array(self):
        assert _parse_json('[1, 2, 3]') == [1, 2, 3]

    def test_strips_code_fences(self):
        assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fixes_trailing_comma(self):
        assert _parse_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        assert _parse_json('[1, 2, 3,]') == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(LlmError, match="Failed to parse"):
            _parse_json("not json at all")

    def test_whitespace_handling(self):
        assert _parse_json('  \n  {"x": 1}  \n  ') == {"x": 1}


class TestOllamaClient:
    @responses.activate
    def test_generate_success(self):
        responses.add(
            responses.POST,
            "http://localhost:11434/api/generate",
            json={"response": '{"page_number": 42}'},
        )
        client = OllamaClient()
        result = client.generate("test prompt")
        assert result == '{"page_number": 42}'

    @responses.activate
    def test_generate_json_success(self):
        responses.add(
            responses.POST,
            "http://localhost:11434/api/generate",
            json={"response": '{"page_number": 42}'},
        )
        client = OllamaClient()
        result = client.generate_json("test prompt")
        assert result == {"page_number": 42}

    @responses.activate
    def test_retry_on_failure(self):
        responses.add(responses.POST, "http://localhost:11434/api/generate", status=500)
        responses.add(
            responses.POST,
            "http://localhost:11434/api/generate",
            json={"response": '{"ok": true}'},
        )
        client = OllamaClient(max_retries=2)
        result = client.generate_json("test")
        assert result == {"ok": True}

    @responses.activate
    def test_all_retries_fail(self):
        responses.add(responses.POST, "http://localhost:11434/api/generate", status=500)
        responses.add(responses.POST, "http://localhost:11434/api/generate", status=500)
        client = OllamaClient(max_retries=2)
        with pytest.raises(LlmError, match="failed after 2 attempts"):
            client.generate("test")

    @responses.activate
    def test_sends_correct_payload(self):
        responses.add(
            responses.POST,
            "http://localhost:11434/api/generate",
            json={"response": "{}"},
        )
        client = OllamaClient(model="custom:7b")
        client.generate("my prompt")
        body = json.loads(responses.calls[0].request.body)
        assert body["model"] == "custom:7b"
        assert body["prompt"] == "my prompt"
        assert body["format"] == "json"
        assert body["stream"] is False

    @responses.activate
    def test_custom_base_url(self):
        responses.add(
            responses.POST,
            "http://myhost:1234/api/generate",
            json={"response": "{}"},
        )
        client = OllamaClient(base_url="http://myhost:1234")
        client.generate("test")
        assert responses.calls[0].request.url == "http://myhost:1234/api/generate"
