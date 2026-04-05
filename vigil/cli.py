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

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from vigil.api.server import start_server
    from vigil.config import load_config
    from vigil.core.orchestrator import Orchestrator
    from vigil.providers import create_provider

    config = load_config(args.config)
    provider = create_provider(config.provider)

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
