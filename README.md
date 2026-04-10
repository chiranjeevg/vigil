<!--
  Canonical repo: https://github.com/chiranjeevg/vigil
  Forks: update chiranjeevg/vigil in links + pyproject.toml [project.urls].
-->
<p align="center">
  <img src="web/public/favicon.svg" width="80" height="80" alt="Vigil" />
</p>

<h1 align="center">Vigil</h1>

<p align="center">
  <strong>Point it at any repo. It keeps improving itself.</strong><br/>
  An autonomous AI agent that writes code, runs tests, and ships improvements — 24/7.<br/>
  Your codebase gets better while you sleep.
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-2563eb?style=for-the-badge" alt="Quick Start" /></a>
  <a href="https://github.com/chiranjeevg/vigil/stargazers"><img src="https://img.shields.io/badge/GitHub-⭐_Star-gold?style=for-the-badge&logo=github&logoColor=white" alt="Star on GitHub" /></a>
  <a href="https://github.com/chiranjeevg/vigil/actions/workflows/ci.yml"><img src="https://img.shields.io/badge/CI-passing-2088FF?style=for-the-badge&logo=githubactions&logoColor=white" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge" alt="MIT License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+" /></a>
</p>

<p align="center">
  <a href="#-see-it-in-action">Demo</a> · <a href="#-what-vigil-does">Features</a> · <a href="#-how-it-works">How It Works</a> · <a href="#-quick-start">Quick Start</a> · <a href="#%EF%B8%8F-configuration">Config</a> · <a href="#-roadmap">Roadmap</a> · <a href="#-contributing">Contributing</a>
</p>

---

## 💡 The Problem

You use AI coding assistants. They're great — **when you're at the keyboard.**

But the moment you close the laptop:

- Tests stay broken.
- Performance regressions sit unnoticed.
- Warnings pile up.
- Tech debt quietly compounds.

You come back the next morning and everything is exactly where you left it.

**What if your repo just… kept getting better on its own?**

---

## 🔍 What Is Vigil?

Vigil is an AI agent you **point at any repository.** It scans the code, figures out what needs fixing, writes the patches, runs your tests — and commits only what passes. Then it does it again. And again. **Continuously.**

```
  You:   git clone my-project && vigil start
  Vigil: *finds 4 untested edge cases, writes tests, passes, commits*
  Vigil: *spots a O(n²) loop, rewrites it, benchmarks +40%, commits*
  Vigil: *removes 12 deprecation warnings, all tests green, commits*
  You:   *wakes up, opens laptop*
  You:   "wait… 9 clean commits overnight?"
```

> **Not a copilot.** It doesn't wait for your prompt. It finds work to do.
> **Not a linter.** It writes and applies actual code changes.
> **Not a CI bot.** It doesn't flag problems — it fixes them.

Point it at a repo. Walk away. Come back to a better codebase.

---

## 🎬 See It In Action

```bash
$ vigil start

🔍 Vigil starting — provider: ollama/qwen3:30b
📋 Iteration 1: optimize_performance — Optimize hot path in parser
   ✅ Tests passed · 2 files changed · +12% throughput
📋 Iteration 2: fix_warnings — Resolve deprecation warnings
   ✅ Tests passed · 4 files changed · 0 warnings remaining
📋 Iteration 3: test_coverage — Add missing edge case tests
   ✅ Tests passed · 3 files changed · 84% → 91% coverage
💤 Sleeping 30s before next iteration…
```

Open the dashboard at **`http://localhost:7420`** — live iterations, diffs, prompts, test results, and benchmarks in one place.

<!-- Add docs/dashboard-preview.png for a screenshot when available. -->

---

## 🚀 What Vigil Does

| | Feature | Why it matters |
|---|---------|----------------|
| 🧪 | **Writes tests automatically** | Wake up to higher coverage — no test-writing sprints |
| ⚡ | **Finds and fixes performance bottlenecks** | Benchmarks gate every commit; regressions are reverted |
| 🧹 | **Removes dead code and warnings** | Clean builds, fewer `// TODO` comments |
| ♻️ | **Modernizes legacy patterns** | Keeps your codebase on current idioms |
| 🔒 | **Catches common security issues** | Flags injection risks, unsafe defaults, missing validation |
| 🧠 | **Deep analysis** | Multi-phase LLM audit: architecture → code tracing → prioritized task plan |
| 🤖 | **Runs with local or cloud LLMs** | Ollama out of the box — no API keys, no cloud dependency |
| 📊 | **Real-time web dashboard** | Watch every iteration live; inspect prompts, diffs, and benchmarks |
| 🔀 | **Git-native: commits or PRs** | Every change is a clean commit; optional PR mode via `gh` CLI |

---

## ⚙️ How It Works

```
         ┌──────────────────────────────────┐
         │          Vigil Loop              │
         │                                  │
         │  1. Pick a task  (by priority)   │
         │  2. Read code    (build context) │
         │  3. Call LLM     (Ollama / API)  │
         │  4. Apply patch  (SEARCH/REPLACE)│
         │  5. Run tests    (your command)  │
         │  6. Benchmark    (revert if ↓)   │
         │  7. Commit / PR                  │
         │  8. Sleep → repeat               │
         └──────────────────────────────────┘
```

Changes are applied via exact **SEARCH/REPLACE** blocks — no blind overwrites. If tests fail or benchmarks regress, Vigil reverts automatically via git. **Your code is always safe.**

---

## 📦 Quick Start

**Prerequisites:** Python 3.11+, [Node.js](https://nodejs.org/) (for the dashboard build via `make install`), and [Ollama](https://ollama.com) running (or any OpenAI-compatible endpoint).

```bash
# 1. Pull a model
ollama pull qwen2.5-coder:14b

# 2. Clone and install (builds the dashboard into the Python package)
git clone https://github.com/chiranjeevg/vigil.git
cd vigil
python -m venv .venv && source .venv/bin/activate
make install

# 3. Configure
cp vigil.example.yaml vigil.yaml
# Edit vigil.yaml — set project.path and tests.command

# 4. Run
vigil start
```

Dashboard opens at **http://localhost:7420**. That's it.

If you only run `pip install -e .` (without `make install`), the API starts but the web UI is unavailable until you run `make build-ui` and reinstall, or copy `web/dist/*` into `vigil/ui/` after building the frontend.

<details>
<summary><strong>One-liner for the bold</strong></summary>

```bash
git clone https://github.com/chiranjeevg/vigil.git && cd vigil && python -m venv .venv && source .venv/bin/activate && make install && cp vigil.example.yaml vigil.yaml && vigil start
```

</details>

---

## ⚖️ How Vigil Compares

Vigil is **not competing with copilots.** Copilots help you write code faster. Vigil works when you're not writing code at all.

| | Vigil | GitHub Copilot | Cursor | Aider | SWE-agent |
|---|:---:|:---:|:---:|:---:|:---:|
| Runs autonomously 24/7 | ✅ | — | — | — | — |
| Local LLM (no cloud) | ✅ | — | — | ✅ | ✅ |
| Web dashboard | ✅ | — | — | — | — |
| Benchmark-gated commits | ✅ | — | — | — | — |
| Test-gated commits | ✅ | — | — | — | — |
| Auto PR workflow | ✅ | — | — | — | ✅ |
| Real-time streaming | ✅ | — | — | — | — |
| Self-hosted, private | ✅ | — | — | ✅ | ✅ |

---

## 🛡️ Safety and Transparency

Transparency builds trust. Here's what Vigil **guarantees** — and what it **doesn't.**

**Safe by design:**
- Every change goes through your test suite before committing.
- Benchmark regressions are **auto-reverted** — performance never silently degrades.
- Read-only paths are respected — mark files Vigil should never touch.
- `dry_run: true` mode lets you see what Vigil *would* do without writing anything.
- Every commit is a clean, reversible git operation.

**Honest limitations:**
- **Not a replacement for code review.** Use PR mode and review changes like any contributor.
- **Not magic.** Output quality depends on the LLM. A local 7B model produces simpler fixes than GPT-4o.
- **Not production-safe by default.** Run on a branch or in dry-run mode first.
- **Not a security tool.** It catches some issues, but don't rely on it for audits.

---

## 🛠️ Configuration

Vigil is configured via `vigil.yaml`. See [`vigil.example.yaml`](vigil.example.yaml) for all options.

| Section | What it controls |
|---------|------------------|
| `project` | Path, language, include/exclude paths, read-only paths |
| `provider` | LLM backend — `ollama` or `openai`, model name, temperature |
| `tests` | Test command, timeout, coverage tracking |
| `benchmarks` | Benchmark command, regression threshold |
| `tasks` | Priority order, custom tasks, per-task LLM instructions |
| `controls` | Safety limits — max iterations, sleep intervals, dry run |
| `pr` | PR workflow — enable per-iteration GitHub PRs |

<details>
<summary><strong>Example: OpenAI</strong></summary>

```yaml
provider:
  type: openai
  model: gpt-4o
  base_url: https://api.openai.com/v1
  api_key_env: OPENAI_API_KEY
```

</details>

<details>
<summary><strong>Example: Custom task</strong></summary>

```yaml
tasks:
  custom:
    - type: "security_audit"
      description: "Find and fix common security vulnerabilities"
      target_files: ["src/auth/", "src/api/"]
      instructions: "Focus on SQL injection, XSS, and auth bypass vectors."
```

</details>

---

## 🏗️ Architecture

```
vigil/
├── cli.py               # CLI entry point (start / stop / status)
├── config.py            # YAML config models (Pydantic)
├── core/
│   ├── orchestrator.py  # Main loop — task → LLM → apply → test → commit
│   ├── code_applier.py  # SEARCH/REPLACE parser and safe file writer
│   ├── git_ops.py       # Git wrapper — commit, revert, diff, branch
│   ├── state.py         # Iteration logging (file + SQLite)
│   ├── benchmark.py     # Benchmark runner and regression gating
│   ├── task_planner.py  # Task selection and rotation
│   ├── deep_suggest.py  # Multi-phase LLM deep analysis pipeline
│   └── pr_manager.py    # GitHub PR creation via gh CLI
├── api/
│   ├── server.py        # FastAPI app + bundled UI from vigil/ui/
│   ├── routes_v2.py     # REST API (DB-backed)
│   └── websocket.py     # Real-time step streaming
├── providers/
│   ├── ollama.py        # Ollama provider
│   └── openai_compat.py # OpenAI-compatible provider
├── prompts/             # System and task prompts for the LLM
└── db/                  # SQLAlchemy models + SQLite session
```

---

## 🗺️ Roadmap

- [x] Autonomous improvement loop with test gating
- [x] Ollama + OpenAI-compatible LLM support
- [x] Real-time web dashboard with iteration inspection
- [x] PR workflow with descriptive branch naming
- [x] Benchmark regression protection
- [x] WebSocket live streaming
- [x] SQLite persistence
- [x] Deep analysis: multi-phase LLM code auditing
- [ ] Multi-project orchestration (parallel)
- [ ] VS Code / Cursor extension
- [ ] GitHub Action for CI-integrated mode
- [ ] Cost tracking and token budgets
- [ ] Plugin system for custom tasks
- [ ] Distributed mode (multiple agents, one codebase)
- [ ] Self-healing: detect and recover from stuck states

---

## 🤝 Contributing

We welcome contributions — from bug reports to new LLM providers. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- 🐛 [Report a bug](https://github.com/chiranjeevg/vigil/issues/new?labels=bug)
- 💡 [Request a feature](https://github.com/chiranjeevg/vigil/issues/new?labels=enhancement)
- 📖 Improve documentation
- 🧪 Add tests
- 🔌 Write a new LLM provider

Look for [`good first issue`](https://github.com/chiranjeevg/vigil/labels/good%20first%20issue) to get started.

## 🔐 Security

Report vulnerabilities responsibly — see [SECURITY.md](SECURITY.md).

## 📄 License

[MIT](LICENSE) — use it, fork it, ship it.

---

<p align="center">
  <strong>Point it at a repo. Walk away. Come back to better code.</strong><br/><br/>
  <a href="https://github.com/chiranjeevg/vigil/stargazers"><img src="https://img.shields.io/badge/⭐_Star_Vigil_on_GitHub-gold?style=for-the-badge&logo=github&logoColor=white" alt="Star Vigil" /></a>
</p>
