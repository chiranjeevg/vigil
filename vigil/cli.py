"""Command-line interface for Vigil."""

import argparse
import json
import signal
import sys

import requests

from vigil import __version__

DEFAULT_API_URL = "http://127.0.0.1:7420"

_orchestrator = None


def _shutdown_handler(signum, frame):
    if _orchestrator:
        _orchestrator.stop()
    sys.exit(0)


def cmd_start(args):
    global _orchestrator

    import logging as _logging
    import os

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from vigil.api.server import start_server
    from vigil.config import load_config
    from vigil.core.orchestrator import Orchestrator
    from vigil.providers import create_provider

    config = load_config(args.config)
    if not (config.project.path or "").strip():
        if os.getenv("VIGIL_USE_DATABASE", "false").lower() == "true":
            import asyncio

            from vigil.daemon_bootstrap import resolve_daemon_config_if_empty_project_path

            try:
                config = asyncio.run(resolve_daemon_config_if_empty_project_path(config))
            except ValueError as e:
                _logging.getLogger(__name__).error("%s", e)
                sys.exit(1)
        else:
            _logging.getLogger(__name__).error(
                "vigil.yaml has no project.path. Set it to your repository root, or set "
                "VIGIL_USE_DATABASE=true and register a project in the dashboard."
            )
            sys.exit(1)

    provider = create_provider(config.provider)

    if os.getenv("VIGIL_USE_DATABASE", "false").lower() != "true":
        from vigil.dev_self import allow_vigil_self_project, is_vigil_source_repo_path

        if is_vigil_source_repo_path(config.project.path) and not allow_vigil_self_project():
            _logging.getLogger(__name__).warning(
                "Config targets the Vigil source checkout. With VIGIL_USE_DATABASE=true the daemon "
                "picks another registered project on startup; in file-only mode set "
                "VIGIL_ALLOW_SELF_PROJECT=1 if you intend to run on this repo."
            )

    _orchestrator = Orchestrator(config, provider)

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    if config.api.enabled:
        start_server(config, _orchestrator, provider)
    else:
        _orchestrator.start()


def cmd_status(args):
    try:
        resp = requests.get(f"{DEFAULT_API_URL}/api/status", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        print(json.dumps(data, indent=2))
    except requests.ConnectionError:
        print("Vigil is not running (cannot connect to API server).")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching status: {e}")
        sys.exit(1)


def cmd_stop(args):
    try:
        resp = requests.post(f"{DEFAULT_API_URL}/api/stop", timeout=5)
        resp.raise_for_status()
        print("Vigil stop signal sent.")
    except requests.ConnectionError:
        print("Vigil is not running (cannot connect to API server).")
        sys.exit(1)
    except Exception as e:
        print(f"Error sending stop: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="vigil",
        description="Vigil — autonomous coding agent that continuously improves codebases",
    )
    parser.add_argument("--version", action="version", version=f"vigil {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start the Vigil orchestrator")
    start_parser.add_argument(
        "--config", default="vigil.yaml", help="Path to config file (default: vigil.yaml)"
    )
    start_parser.set_defaults(func=cmd_start)

    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.set_defaults(func=cmd_status)

    stop_parser = subparsers.add_parser("stop", help="Stop Vigil gracefully")
    stop_parser.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    args.func(args)
