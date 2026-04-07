"""Tests for LLM prompt sanitization."""

from vigil.providers.base import sanitize_llm_text


def test_sanitize_llm_text_preserves_normal_text():
    s = "hello\nworld\t[SYSTEM]"
    assert sanitize_llm_text(s) == s


def test_sanitize_llm_text_strips_nul_bytes():
    raw = "a\x00b\x00c"
    assert sanitize_llm_text(raw) == "abc"


def test_sanitize_llm_text_empty():
    assert sanitize_llm_text("") == ""
