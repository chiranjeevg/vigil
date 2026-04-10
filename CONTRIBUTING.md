# Contributing to Vigil

Thanks for your interest in contributing to Vigil! Every contribution matters — whether it's a bug report, documentation fix, or a new feature.

## Getting Started

### Development Setup

```bash
# Fork and clone (use your fork’s URL if you are not pushing upstream)
git clone https://github.com/chiranjeevg/vigil.git
cd vigil

# Python setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Frontend setup
cd web
npm install
npm run dev  # starts dev server with hot reload on :5173
```

### Running Vigil Locally

```bash
# Copy config
cp vigil.example.yaml vigil.yaml
# Edit vigil.yaml — set project.path and provider settings

# Start the backend (serves API + dashboard)
vigil start

# In another terminal, run the frontend dev server (optional, for UI work)
cd web && npm run dev
```

### Project Structure

```
vigil/          Python package (backend)
├── cli.py      CLI entry point
├── config.py   Config models
├── core/       Orchestrator, git, code applier, state
├── api/        FastAPI routes + WebSocket
├── providers/  LLM backends (Ollama, OpenAI-compat)
├── prompts/    System/task prompts
└── db/         SQLAlchemy models + session

web/            React + TypeScript frontend (sources)
├── src/pages/  Dashboard, Logs, Settings, Tasks, Setup
├── src/lib/    API client
└── src/hooks/  usePolling, useWebSocket

vigil/ui/       Bundled dashboard static files (`make build-ui` copies `web/dist/` here)
```

## How to Contribute

### Reporting Bugs

Open an [issue](https://github.com/chiranjeevg/vigil/issues/new?labels=bug) with:
- Steps to reproduce
- Expected vs actual behavior
- Vigil version (`vigil --version`)
- LLM provider and model used
- Relevant log output (`tail -f /tmp/vigil.log`)

### Suggesting Features

Open an [issue](https://github.com/chiranjeevg/vigil/issues/new?labels=enhancement) with:
- The problem you're trying to solve
- Your proposed solution
- Alternatives you've considered

### Submitting Code

1. Fork the repo and create a branch: `git checkout -b feat/my-feature`
2. Make your changes
3. Run checks (same as [CI](.github/workflows/ci.yml)):
   - `ruff check vigil/`
   - `pytest -q` (from repo root, with dev deps installed)
   - `make build-ui` (or `cd web && npm ci && npm run build` — use `make build-ui` to also populate `vigil/ui/` for local `vigil start`)
4. Test manually when relevant: `vigil start` and verify behavior
5. Commit with a clear message
6. Open a pull request

**Forks:** If you publish under your own GitHub org, update `homepage` / `repository` / `issues` in `pyproject.toml` and badge URLs in `README.md` to match your fork.

### Code Style

**Python:**
- Follow PEP 8 with 120 char line length
- Use type hints for function signatures
- Add docstrings to public classes and functions
- Run `ruff check --fix vigil/` before committing

**TypeScript:**
- Use TypeScript strict mode
- Prefer functional components with hooks
- Keep components small and focused

### Areas Where Help Is Needed

- **Testing** — We need unit and integration tests across the board
- **Providers** — New LLM provider backends (Anthropic, Google, local GGUF, etc.)
- **Documentation** — Usage guides, tutorials, deployment docs
- **Security** — Audit the code applier and git operations
- **Performance** — Optimize large file handling and context building
- **UI/UX** — Dashboard polish, mobile responsiveness, accessibility

### Good First Issues

Look for issues tagged [`good first issue`](https://github.com/chiranjeevg/vigil/labels/good%20first%20issue). These are scoped, well-described tasks ideal for newcomers.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Questions?

Open a [discussion](https://github.com/chiranjeevg/vigil/discussions) or reach out in issues. We're friendly.
