# Contributing to JiuMe

Thanks for helping make JiuMe better. The most valuable contributions keep the project local-first, testable, and honest about what actually runs.

## Development Setup

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"
```

If you do not use `uv`, a standard virtual environment also works:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[test]"
```

## Before Opening a Pull Request

Run the focused checks:

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume
git diff --check
```

For launcher-related changes, also run:

```bash
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
```

## Contribution Guidelines

- Keep user-facing claims grounded in real runtime behavior.
- Prefer local-first storage and explicit user review for personal data, identity, photos, and distilled memories.
- Do not commit generated avatar previews, `.superpowers/`, local workspace data, logs, or API keys.
- Add or update focused tests for JiuMe behavior you change.
- Keep JiuMe-specific code in `jiume/` unless a runtime bridge requires a small, explicit change in `jiuwenswarm/`.
- Document any new external provider, credential, or network behavior in the README or JiuMe docs.

## Pull Request Checklist

- [ ] The change has a clear user-facing reason.
- [ ] JiuMe-focused tests pass locally or the PR explains why they could not be run.
- [ ] No secrets, local twin data, personal chat exports, or generated private avatar assets are committed.
- [ ] Documentation is updated when commands, setup, configuration, or product behavior changes.

## Reporting Issues

Use the GitHub issue templates when possible. Include the exact command, OS, Python version, and whether the failure happens with a clean local data directory.
