# JiuMe Human Desktop Twin MVP

JiuMe is a standalone desktop companion for a personal Agent. The daily surface is intentionally small: an always-on avatar that can stay on the desktop without feeling like a control panel. Setup and advanced management still exist, but the everyday loop is one-line and avatar-first.

## What Is Included

- Avatar-only daily surface: `jiume` or `jiume-avatar` opens a transparent, always-on-top avatar that can be dragged across screens and remembers position, size, and opacity. By default, it does not show a toolbar, panel grid, or command shelf.
- One-line task flow: click avatar -> type one line -> JiuMe sends the request to the Agent and handles the rest. While work is running, JiuMe shows only a short task capsule. When the Agent needs clarification or approval, JiuMe asks one question. When work finishes, it collapses into one short result.
- Quiet shell menu: right-click and the app menu expose only Settings and Quit JiuMe in the daily shell. This keeps JiuMe comfortable to leave on the desktop for long stretches.
- Setup and advanced settings: first-run setup remains the required place to create or configure the local twin. Settings/Advanced contains model and API configuration, Gateway diagnostics, skill management, artifacts, full task history, desktop placement, avatar profile, permissions, and troubleshooting.
- Gateway bridge: the desktop twin connects to `ws://127.0.0.1:19000/ws` by default, sends user text through `chat.send`, and maps streaming replies, tool calls, approval waits, completion, and errors back into avatar states and task capsules.
- Desktop identity: each twin has profile data, local avatar assets, remembered desktop state, recent conversation state, and runtime task state under the JiuMe data directory.

## Quick Start

```bash
git clone https://github.com/XiaoLuoLYG/jiume.git
cd jiume

# First run or after dependency changes
uv venv --python 3.11 --seed .venv
uv pip install -e ".[test]"

# Start Setup, Agent/Gateway, and the desktop twin with one command
.venv/bin/jiume-launch --open-setup
```

Install JiuMe as a login item:

```bash
.venv/bin/jiume-launch --install-login-item
.venv/bin/jiume-launch --login-item-status
.venv/bin/jiume-launch --uninstall-login-item
```

By default, `jiume-launch` reuses already-running Setup/Gateway services and restarts only the child services that it started. Disable service restart while debugging:

```bash
.venv/bin/jiume-launch --no-service-restart
```

For split debugging:

```bash
# Start setup
.venv/bin/jiume-setup --open

# In another terminal, start the desktop twin
.venv/bin/jiume
```

To inspect the UI without Gateway:

```bash
.venv/bin/jiume --gateway-url ""
```

## Image Generation Config

JiuMe image generation config can be saved in the Setup page or exported before starting `jiume-setup`.

- `JIUME_OPENAI_API_KEY`: image generation API key, preferred over `OPENAI_API_KEY`.
- `JIUME_OPENAI_BASE_URL`: OpenAI-compatible base URL, preferred over `OPENAI_BASE_URL`.
- `JIUME_IMAGE_MODEL`: image generation model, default `gpt-image-2`.
- `JIUME_IMAGE_PROVIDER`: `openai`, `mock`, or `auto`.

Uploads are optional and require explicit consent. If no image provider key is configured, JiuMe uses local transparent Q-style avatar assets.

## State Control

```bash
.venv/bin/jiume-state idle
.venv/bin/jiume-state thinking
.venv/bin/jiume-state working
.venv/bin/jiume-state waiting_approval
.venv/bin/jiume-state success
.venv/bin/jiume-state error
.venv/bin/jiume-state sleep
```

## Data Layout

```text
~/.jiuwenswarm/
  jiume/config.env
  jiume/desktop_state.json
  jiume/window_state.json
  jiume/conversation_state.json
  jiume/companion_state.json
  jiume/screen_context/
  jiume/twins/{twin_id}/profile.json
  jiume/twins/{twin_id}/memory.json
  jiume/twins/{twin_id}/avatar/
  jiume/twins/{twin_id}/audit/events.jsonl
  jiume/twins/{twin_id}/distill/jobs/{job_id}/job.json
```

## Verification

```bash
.venv/bin/python -m compileall -q jiume jiuwenswarm/start_services.py
.venv/bin/python -m pytest -q --no-cov tests/unit_tests/jiume/test_twin_store.py
.venv/bin/python -m jiume.launcher --help
.venv/bin/python -m jiume.launcher --login-item-status
git diff --check
```

## Current MVP Limits

- JiuMe currently prioritizes a low-noise daily desktop loop over feature discovery. Rich controls live in Settings/Advanced until they can be reintroduced without making the avatar feel like a panel.
- Rich artifact editing, remote skill marketplace installation, and more detailed task-history browsing still need product work inside the advanced surfaces.
