# Contributing to JiuMe

Thanks for helping make JiuMe better. The best contributions make the local desktop experience clearer, safer, or easier to try.

## Start Here

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"
.venv/bin/jiume-launch --open-setup
```

If you do not use `uv`, a normal Python 3.11 virtual environment also works.

## Good First Contributions

- Make first-run setup clearer.
- Improve the avatar-first desktop flow.
- Simplify docs, screenshots, or error messages.
- Add focused tests for JiuMe behavior.
- Fix bugs that reproduce locally without private credentials.

## Before Opening a PR

Run:

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume
git diff --check
```

For launcher changes, also run:

```bash
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
```

## Project Rules

- Keep product claims grounded in real local behavior.
- Keep personal data local-first and review-gated.
- Do not commit API keys, `~/.jiuwenswarm/jiume/` data, private photos, chat exports, logs, or local workspace files.
- Keep JiuMe-specific code in `jiume/` unless a runtime bridge needs a small change in `jiuwenswarm/`.
- Update README or `docs/en/JiuMe.md` / `docs/zh/JiuMe.md` when setup, commands, config, or visible behavior changes.

## Issue Reports

Please include:

- the command you ran
- OS and Python version
- expected behavior
- actual behavior
- a minimal reproduction using fake data

Redact secrets and personal data before posting.
