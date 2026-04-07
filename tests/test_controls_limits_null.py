"""Optional null limits in ControlsConfig."""

from vigil.config import VigilConfig


def _minimal_project(path: str = "/tmp/x") -> dict:
    return {
        "project": {"name": "t", "path": path},
        "controls": {},
    }


def test_defaults_when_omitted():
    c = VigilConfig(**_minimal_project())
    assert c.controls.max_files_per_iteration == 5
    assert c.controls.max_lines_changed == 200


def test_null_means_unlimited():
    raw = _minimal_project()
    raw["controls"] = {
        "max_files_per_iteration": None,
        "max_lines_changed": None,
    }
    c = VigilConfig(**raw)
    assert c.controls.max_files_per_iteration is None
    assert c.controls.max_lines_changed is None


def test_mixed_null_and_int():
    raw = _minimal_project()
    raw["controls"] = {
        "max_files_per_iteration": None,
        "max_lines_changed": 500,
    }
    c = VigilConfig(**raw)
    assert c.controls.max_files_per_iteration is None
    assert c.controls.max_lines_changed == 500
