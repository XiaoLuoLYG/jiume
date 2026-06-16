<div align="center">

# JiuMe

Local-first desktop digital twin for personal agents.

[![CI](https://github.com/XiaoLuoLYG/jiume/actions/workflows/ci.yml/badge.svg)](https://github.com/XiaoLuoLYG/jiume/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

</div>

JiuMe is a desktop companion layer on top of the JiuwenSwarm agent runtime. It gives a personal agent a small always-on avatar, a one-line task entry point, local twin profile/state, mounted personal skills, and a review-gated personal distillation loop.

The project is intentionally local-first: runtime configuration, twin profile data, avatar assets, audit logs, and distilled personal artifacts are stored on the user's machine. External model or image-generation providers are optional and must be configured explicitly.

## Current Status

JiuMe is an early source-release project. The desktop avatar, setup server, runtime bridge, local twin store, skill mounting, and personal distillation primitives are present. The current focus is making the local MVP reliable and transparent rather than claiming a finished consumer app.

Primary platform today is macOS with Python 3.11+. The underlying web/runtime services are Python-based and are tested without requiring cloud credentials.

## What Is Included

- Desktop avatar shell: a transparent, always-on-top companion window launched with `jiume` or `jiume-avatar`.
- One-line task loop: click/type/send, then JiuMe maps agent progress, tool calls, approval waits, completion, and failures back into compact desktop states.
- Setup server: first-run configuration for twin identity, model/image provider settings, and runtime diagnostics.
- JiuwenSwarm runtime bridge: `chat.send` requests can carry active JiuMe twin context into the real agent path.
- Local twin data: profile, memories, permissions, mounted skills, avatar assets, audit events, and desktop state live under `~/.jiuwenswarm/jiume/`.
- Personal distillation engine: converts reviewed chat/task/source snippets into layered profile, style, procedural, and personal-skill artifacts before installation.
- Tests for the JiuMe-specific runtime, twin store, setup/settings behavior, one-line companion flow, and personal distillation path.

## Quick Start

Clone the repository:

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume
```

Create a local environment and install the project:

```bash
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"
```

Start setup, the JiuwenSwarm runtime, and the desktop twin:

```bash
.venv/bin/jiume-launch --open-setup
```

For split debugging:

```bash
.venv/bin/jiume-setup --open
.venv/bin/jiume
```

To inspect the avatar UI without a gateway connection:

```bash
.venv/bin/jiume --gateway-url ""
```

## Configuration

Image generation is optional. Without a configured provider, JiuMe uses local generated/mock avatar assets so the app can still run end to end.

Relevant environment variables:

```bash
export JIUME_OPENAI_API_KEY="..."
export JIUME_OPENAI_BASE_URL="https://api.openai.com/v1"
export JIUME_IMAGE_MODEL="gpt-image-2"
export JIUME_IMAGE_PROVIDER="auto"
```

The setup UI can also persist these values to:

```text
~/.jiuwenswarm/jiume/config.env
```

User photo uploads and durable personal-distillation writes are intended to be explicit, local-first, and review-gated.

## Repository Layout

```text
jiume/                         JiuMe product layer
  desktop/                     Avatar shell, desktop state, native interactions
  setup/                       First-run setup server
  runtime/                     Gateway health and twin-context injection
  twins/                       File-backed twin profile and memory store
  skills/                      Local skill catalog and installation helpers
  personal_distillation/       Review-gated memory/skill distillation engine
  avatar/                      Avatar asset generation and manifests
jiuwenswarm/                   JiuwenSwarm runtime used by JiuMe
jiuwenbox/                     Local sandbox/proxy package used by the runtime
tests/unit_tests/jiume/        JiuMe-focused unit tests
docs/en/JiuMe.md               Detailed English MVP notes
docs/zh/JiuMe.md               Detailed Chinese MVP notes
```

## Development

Run the focused JiuMe checks:

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume
git diff --check
```

Run launcher smoke commands:

```bash
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
```

## Documentation

- [JiuMe MVP notes](docs/en/JiuMe.md)
- [中文说明](README_CN.md)
- [JiuwenSwarm memory docs](docs/en/Memory.md)
- [JiuwenSwarm skill self-evolution docs](docs/en/SkillSelfEvolution.md)
- [Testing guide](TESTING.md)

## Contributing

Contributions are welcome when they keep the project honest about what really runs locally. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

Please do not publish real API keys, personal chat exports, private avatar source images, or local twin data in issues or pull requests. See [SECURITY.md](SECURITY.md) for reporting guidance.

## License

JiuMe is released under the [Apache License 2.0](LICENSE). It builds on JiuwenSwarm code in this repository, which is also Apache-2.0 licensed.
