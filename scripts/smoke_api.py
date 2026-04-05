#!/usr/bin/env python3
"""Smoke-test API: CORS OPTIONS preflight + POST /api/projects/remove (expects 400 invalid path).

Run from repo root:
  VIGIL_USE_DATABASE=true python scripts/smoke_api.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    os.chdir(REPO)
    os.environ.setdefault("VIGIL_USE_DATABASE", "true")

    from fastapi.testclient import TestClient

    from vigil.api.server import create_app
    from vigil.config import load_config

    cfg_path = REPO / "vigil.yaml"
    if not cfg_path.is_file():
        print("FAIL: vigil.yaml not found at repo root (needed for smoke test)", file=sys.stderr)
        return 1

    cfg = load_config(str(cfg_path))

    class Dummy:
        pass

    app = create_app(cfg, Dummy(), None)
    with TestClient(app) as client:
        r = client.options(
            "/api/projects/remove",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        if r.status_code != 200:
            print("FAIL OPTIONS", r.status_code, r.text, file=sys.stderr)
            return 1

        r2 = client.post("/api/projects/remove", json={"path": "/__nonexistent_vigil_path__"})
        if r2.status_code != 400:
            print("FAIL POST", r2.status_code, r2.text, file=sys.stderr)
            return 1

    print("smoke_api: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
