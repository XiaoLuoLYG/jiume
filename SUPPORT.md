# Support

JiuMe is an early source-release project. The fastest way to get useful help is to report the exact local behavior you see.

## Before Asking for Help

Run:

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q tests/unit_tests/jiume
.venv/bin/python -m jiume.launcher --help
```

Include the command output if it is relevant, but redact secrets and local personal data.

## Where to Ask

- Bugs: use the bug report issue template.
- Feature requests: use the feature request template.
- Security issues: follow `SECURITY.md`.

## What Not to Share

Do not upload real API keys, `~/.jiuwenswarm/jiume/` data, personal chat exports, private avatar source photos, or logs containing private user content.
