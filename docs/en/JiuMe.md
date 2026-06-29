# JiuMe Practical Guide

JiuMe is the desktop layer for a personal agent. The daily surface stays small on purpose: an avatar on your desktop, a one-line task composer, and local twin data that only becomes durable after review.

![JiuMe one-line task screenshot](../assets/jiume/one-line-real.svg)

## First Run

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume

uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"

.venv/bin/jiume-launch --open-setup
```

Use this path first. It starts Setup, the local JiuwenSwarm runtime, and the desktop avatar together.

## Daily Use

1. Click the avatar.
2. Type one-line task text.
3. Send it to the agent.
4. Review any permission, memory, or skill updates before they are saved.

JiuMe maps agent progress into simple states: idle, thinking, working, waiting for approval, success, error, and sleep. The goal is to keep the desktop surface calm while the real runtime does the work.

![JiuMe settings screenshot](../assets/jiume/settings-real.svg)

## Useful Commands

Start the full local experience:

```bash
.venv/bin/jiume-launch --open-setup
```

Open the setup page only:

```bash
.venv/bin/jiume-setup --open
```

Open the avatar without a Gateway connection:

```bash
.venv/bin/jiume --gateway-url ""
```

Install, inspect, or remove the macOS login item:

```bash
.venv/bin/jiume-launch --install-login-item
.venv/bin/jiume-launch --login-item-status
.venv/bin/jiume-launch --uninstall-login-item
```

Manually set the avatar state while testing:

```bash
.venv/bin/jiume-state idle
.venv/bin/jiume-state thinking
.venv/bin/jiume-state working
.venv/bin/jiume-state waiting_approval
.venv/bin/jiume-state success
.venv/bin/jiume-state error
.venv/bin/jiume-state sleep
```

## Avatar Pet Package

JiuMe does not generate avatar art in-app. Generate a Codex pet with `hatch-pet` or download an existing Codex pet package, then import its folder or ZIP:

```bash
.venv/bin/jiume-setup --pet ~/.codex/pets/my-pet --enable
```

The package must contain `pet.json` and `spritesheet.webp`.

## Local Data

JiuMe keeps its own data under `~/.jiuwenswarm/jiume/`:

```text
config.env
desktop_state.json
window_state.json
conversation_state.json
companion_state.json
twins/{twin_id}/profile.json
twins/{twin_id}/memory.json
twins/{twin_id}/avatar/
twins/{twin_id}/audit/events.jsonl
twins/{twin_id}/distill/jobs/{job_id}/job.json
```

Do not share this directory in issues or pull requests. It can contain private identity, chat, avatar, and memory data.

## How Learning Works

![JiuMe progress screenshot](../assets/jiume/progress-real.svg)

JiuMe can turn reviewed conversations, tasks, and source snippets into:

- profile notes
- communication style
- procedural memory
- personal skill drafts

The important rule is simple: durable personal learning is review-gated.

## Troubleshooting

- If the avatar does not appear, run `.venv/bin/jiume --gateway-url ""` to check the UI by itself.
- If Setup opens but tasks do not run, restart with `.venv/bin/jiume-launch --open-setup`.
- If a test or command behaves strangely, try a fresh data directory by setting `JIUWENSWARM_DATA_DIR` to a temporary path before launching.
- If you report a bug, include the command, macOS/Python version, and the visible error. Redact secrets and personal data.

## Verification

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume
git diff --check
```
