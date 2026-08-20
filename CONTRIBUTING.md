# Contributing to Analytics Toolkit

Thank you for helping make journey analysis clearer, safer, and more useful.

## Before you start

- Search existing issues before opening a new one.
- Use a discussion for broad product ideas and an issue for bounded work.
- Never include production analytics rows, identifiers, credentials, or customer data.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
make test
```

## Pull requests

Keep changes focused, add tests, run `make check`, include mobile screenshots for UI work, and document changes to journey semantics, denominators, identity rules, query cost, or privacy behavior.

## Validate your change

- SignalCheck: run `npm test` and `npm run build`.
- PathFinder: run `make test` from `tools/pathfinder`.
- Full toolkit: run `make check` from the repository root.

## Design principles

- Prefer decision-ready answers over chart density.
- Keep session-based denominators explicit.
- Preserve ambiguity rather than inventing identity certainty.
- Keep the core interface usable without third-party frontend assets.
- Treat BigQuery scan size as a product constraint.
- Keep Gemini credentials behind the Cloudflare Worker boundary.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
