"""Tests for LLM JSON extraction and repair helpers in deep_suggest."""

import json

import pytest

from vigil.core.deep_suggest import (
    _extract_json,
    _loads_json_lenient,
    _repair_invalid_json_escapes,
    _repair_trailing_commas,
)


def test_repair_trailing_commas_object_and_array() -> None:
    raw = '{"a": 1, "b": [2, 3,],}'
    fixed = _repair_trailing_commas(raw)
    assert json.loads(fixed) == {"a": 1, "b": [2, 3]}


def test_repair_invalid_escape_windows_path_like() -> None:
    # Invalid JSON: lone backslash before P
    bad = r'{"file":"src\pkg\main.go"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)
    fixed = _repair_invalid_json_escapes(bad)
    assert json.loads(fixed) == {"file": r"src\pkg\main.go"}


def test_repair_preserves_valid_escapes() -> None:
    ok = r'{"a":"line\nb\"c","b":"\\\\"}'
    assert _repair_invalid_json_escapes(ok) == ok
    assert json.loads(_repair_invalid_json_escapes(ok)) == json.loads(ok)


def test_loads_json_lenient_applies_repairs() -> None:
    # JSON treats \t, \f, \b etc. as escapes — use paths where \ is invalid (e.g. \p, \m)
    bad = r'{"x": [1, 2,], "p":"src\pkg\main.go"}'
    obj = _loads_json_lenient(bad)
    assert obj["x"] == [1, 2]
    assert obj["p"] == r"src\pkg\main.go"


def test_extract_json_fenced_and_repairs() -> None:
    body = r'''```json
{
  "findings": [{"title": "x", "path": "a\b\c"}],
}
```'''
    out = _extract_json(body)
    assert isinstance(out, dict)
    assert len(out["findings"]) == 1


def test_extract_json_prefers_balanced_when_first_last_invalid() -> None:
    # first { to last } is invalid (two objects); balanced scan yields first object
    text = '{"tasks": [1]} garbage {"tasks": [2]}'
    out = _extract_json(text)
    assert out == {"tasks": [1]}


def test_repair_backslash_literal_newline_in_string() -> None:
    # Invalid JSON: backslash then real newline inside string
    bad = '{"a":"line1\\\nline2"}'
    # Above: after line1 we have \ + newline — in Python source this is tricky
    bad = '{"a":"line1\\' + "\n" + 'line2"}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)
    fixed = _repair_invalid_json_escapes(bad)
    assert json.loads(fixed)["a"] == "line1\nline2"
