"""Tests for CodeApplier.validate_changes safety limits."""

from vigil.core.code_applier import CodeApplier


def _applier() -> CodeApplier:
    return CodeApplier("/tmp", read_only_paths=[])


def test_validate_ok_within_limits():
    a = _applier()
    changes = [
        {"file": "a.py", "lines_changed": 10},
        {"file": "b.py", "lines_changed": 20},
    ]
    ok, msg = a.validate_changes(changes, max_files=5, max_lines=200)
    assert ok is True
    assert msg == ""


def test_validate_fails_file_count_with_paths():
    a = _applier()
    changes = [{"file": f"f{i}.py", "lines_changed": 1} for i in range(6)]
    ok, msg = a.validate_changes(changes, max_files=5, max_lines=10_000)
    assert ok is False
    assert "6 files were modified" in msg
    assert "max_files_per_iteration is 5" in msg
    assert "f0.py" in msg and "f5.py" in msg


def test_validate_fails_line_total():
    a = _applier()
    changes = [
        {"file": "big.py", "lines_changed": 150},
        {"file": "other.py", "lines_changed": 100},
    ]
    ok, msg = a.validate_changes(changes, max_files=10, max_lines=200)
    assert ok is False
    assert "250" in msg
    assert "max_lines_changed is 200" in msg
    assert "big.py" in msg


def test_validate_unlimited_files():
    a = _applier()
    changes = [{"file": f"f{i}.py", "lines_changed": 1} for i in range(50)]
    ok, msg = a.validate_changes(changes, max_files=None, max_lines=10_000)
    assert ok is True
    assert msg == ""


def test_validate_unlimited_lines():
    a = _applier()
    changes = [{"file": "a.py", "lines_changed": 99999}]
    ok, msg = a.validate_changes(changes, max_files=5, max_lines=None)
    assert ok is True
    assert msg == ""


def test_validate_both_unlimited():
    a = _applier()
    changes = [{"file": f"f{i}.py", "lines_changed": 1000} for i in range(100)]
    ok, msg = a.validate_changes(changes, max_files=None, max_lines=None)
    assert ok is True
