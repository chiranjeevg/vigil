# Security

## Reporting a vulnerability

Please **do not** open a public GitHub issue for undisclosed security vulnerabilities.

Instead, report details privately:

1. Open a **Security Advisory** on this repository’s GitHub **Security** tab (Advisories → Report a vulnerability), **or**
2. Email maintainers with a clear subject line (e.g. `[SECURITY] Vigil — brief description`).

Include:

- Affected component (CLI, API, web UI, code applier, etc.)
- Steps to reproduce or proof-of-concept
- Suggested severity (if known)

We aim to acknowledge within a few business days and coordinate disclosure after a fix is available.

## Scope

Vigil runs LLM-generated code and shell commands **on your machine** against **your** repositories. Treat your `vigil.yaml`, API keys (via environment variables), and network exposure (API bind address) as sensitive operational configuration.

## Secure configuration tips

- Prefer binding the API to `127.0.0.1` unless you understand the network risk.
- Use least-privilege paths in `read_only_paths` and `exclude_paths`.
- Do not commit `vigil.yaml` with secrets — it is gitignored by default; use `vigil.example.yaml` as a template.
