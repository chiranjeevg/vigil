"""History-based priority rotation for the improver mode walk."""

from vigil.core.task_planner import _rotate_priorities_from_history


def test_single_success_moves_to_end():
    assert _rotate_priorities_from_history(
        ["security_audit", "error_handling", "add_logging"],
        [{"task_type": "security_audit", "status": "success"}],
    ) == ["error_handling", "add_logging", "security_audit"]


def test_two_iterations_advances_past_both():
    """After A-success then B-success, the next pick should be C."""
    result = _rotate_priorities_from_history(
        ["security_audit", "error_handling", "add_logging", "add_tests"],
        [
            {"task_type": "security_audit", "status": "success"},
            {"task_type": "error_handling", "status": "success"},
        ],
    )
    assert result == ["add_logging", "add_tests", "security_audit", "error_handling"]


def test_failure_also_rotates():
    """Failed iterations must rotate too; otherwise the planner retries the same task."""
    assert _rotate_priorities_from_history(
        ["security_audit", "error_handling", "add_logging"],
        [{"task_type": "security_audit", "status": "safety_revert"}],
    ) == ["error_handling", "add_logging", "security_audit"]


def test_mixed_success_and_failure_advances():
    """A-success, B-failure should still advance to C."""
    result = _rotate_priorities_from_history(
        ["A", "B", "C", "D"],
        [
            {"task_type": "A", "status": "success"},
            {"task_type": "B", "status": "safety_revert"},
        ],
    )
    assert result[0] == "C"


def test_full_cycle_wraps_back():
    """After all priorities attempted, the order wraps back."""
    result = _rotate_priorities_from_history(
        ["A", "B", "C"],
        [
            {"task_type": "A", "status": "success"},
            {"task_type": "B", "status": "success"},
            {"task_type": "C", "status": "success"},
        ],
    )
    assert result == ["A", "B", "C"]


def test_ping_pong_scenario():
    """Reproduces the bug: A→B→A→B should still advance to C."""
    result = _rotate_priorities_from_history(
        ["security_audit", "error_handling", "add_logging", "add_tests"],
        [
            {"task_type": "security_audit", "status": "success"},
            {"task_type": "error_handling", "status": "success"},
            {"task_type": "security_audit", "status": "success"},
        ],
    )
    assert result[0] == "add_logging"


def test_unknown_task_type_ignored():
    assert _rotate_priorities_from_history(
        ["A", "B"],
        [{"task_type": "unknown_task", "status": "success"}],
    ) == ["A", "B"]


def test_empty_history():
    assert _rotate_priorities_from_history(["A", "B", "C"], []) == ["A", "B", "C"]


def test_missing_task_type_key():
    assert _rotate_priorities_from_history(
        ["A", "B"], [{"status": "success"}]
    ) == ["A", "B"]
