# Security Policy

JiuMe handles local identity data, avatar inputs, chat-derived context, personal skill drafts, and API credentials. Treat those files as private user data.

## Supported Versions

The public source release is currently pre-1.0. Security fixes target the default branch until stable version branches exist.

## Reporting a Vulnerability

Please do not disclose security issues in a public issue before maintainers have had a chance to investigate.

Preferred reporting path:

1. Open a private GitHub security advisory for `XiaoLuoLYG/jiume` when available.
2. If private advisories are unavailable, open a minimal public issue that says a private security report is needed, without exploit details or private data.

Useful details:

- affected commit or version
- operating system and Python version
- exact local command or UI path
- whether real API keys, photos, chat exports, or twin data were involved
- minimal reproduction that uses fake credentials and synthetic data

## Data Handling Expectations

- Never attach real `~/.jiuwenswarm/jiume/` data to an issue.
- Redact API keys, tokens, personal names, addresses, screenshots, photos, and chat exports.
- Prefer synthetic test data for reproductions.
- Keep irreversible actions, external messages, calendar changes, payments, and durable identity updates behind explicit user approval.
