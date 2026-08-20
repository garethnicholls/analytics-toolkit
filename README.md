# Analytics Toolkit

<p align="center"><strong>Practical, privacy-aware tools for analytics quality and journey understanding.</strong></p>
<p align="center">
  <img alt="TypeScript" src="https://img.shields.io/badge/SignalCheck-TypeScript-3178C6?logo=typescript&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/PathFinder-Python-3776AB?logo=python&logoColor=white">
  <img alt="Cloudflare" src="https://img.shields.io/badge/runtime-Cloudflare-F38020?logo=cloudflare&logoColor=white">
  <img alt="Privacy aware" src="https://img.shields.io/badge/design-privacy--aware-168A65">
</p>

Analytics Toolkit brings implementation QA and event-centred journey analysis into one repository. The tools share a clear philosophy: deterministic checks first, explicit privacy boundaries, understandable outputs, and interfaces designed for real analytical work.

## Tools

| Tool | Purpose | Stack | Status |
| --- | --- | --- | --- |
| **SignalCheck** | Audit analytics payloads for naming problems, empty values, and likely PII; optionally generate a deeper Gemini review or QA plan. | React, TypeScript, Cloudflare Workers | Active |
| **[GA4 PathFinder](tools/pathfinder/)** | Explore what happens before and after important events in the raw GA4 BigQuery export. | Python, pandas, native web UI | Active |

## SignalCheck

SignalCheck is the root application. Deterministic rules run locally and the optional AI audit is handled by a Cloudflare Worker so the Gemini key never enters browser code.

```bash
npm install
cp .dev.vars.example .dev.vars
# Add GEMINI_API_KEY to .dev.vars for optional AI analysis
npm run dev
```

Validate or deploy with `npm test`, `npm run build`, and `npm run deploy`.

`GEMINI_API_KEY` must remain a Worker secret. Never place it in source code, `wrangler.jsonc`, or a `VITE_` variable. `/api/health` reports configuration status without revealing the key.

## GA4 PathFinder

<p align="center"><img src="tools/pathfinder/docs/hero.svg" alt="GA4 PathFinder event-centred journey readout" width="100%"></p>

PathFinder converts event-level GA4 data into a focused journey readout: dominant routes before and after an event, continuation and stopping rates, configured outcomes, alternatives, and repeated route windows.

```bash
cd tools/pathfinder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python web_app.py
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Synthetic data is ready immediately; BigQuery instructions and journey semantics are in the [PathFinder guide](tools/pathfinder/README.md).

## Repository map

```text
analytics-toolkit/
├── src/                  SignalCheck React application
├── worker/               Cloudflare Worker and Gemini boundary
├── tests/                SignalCheck unit tests
├── tools/pathfinder/     GA4 PathFinder application and tests
├── .github/              CI, security, updates, and contribution workflows
└── wrangler.jsonc        SignalCheck deployment configuration
```

## Validate everything

Run `make check` to execute the SignalCheck test/build pipeline and the complete PathFinder Python suite. GitHub Actions runs both independently on every pull request, with CodeQL and Dependabot covering both ecosystems.

## Data safety

- Remove or mask customer identifiers before testing payloads.
- Never commit `.dev.vars`, `.env`, Google credentials, or service-account keys.
- Keep AI keys in Worker secrets and Google access in Application Default Credentials.
- PathFinder excludes raw component values and uses hashed browser/session identifiers.
- Start BigQuery analysis with narrow date ranges and retain the billing guard.

See [SECURITY.md](SECURITY.md) for private vulnerability reporting and [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
