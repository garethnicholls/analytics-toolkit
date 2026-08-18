# SignalCheck Analytics Toolkit

React, TypeScript and Cloudflare Workers app for analytics implementation QA. It runs deterministic event naming, empty-value and likely-PII checks, then optionally asks Gemini for a deeper audit or journey-specific QA plan.

## Local setup

```bash
npm install
cp .dev.vars.example .dev.vars
# Add your Google AI Studio key to .dev.vars
npm run dev
```

## Cloudflare setup

```bash
npx wrangler login
npx wrangler secret put GEMINI_API_KEY
npm run deploy
```

`GEMINI_API_KEY` is used only by the Worker. Never put it in source code, `wrangler.jsonc`, or a `VITE_` variable. The app also exposes `/api/health`, which reports whether Gemini is configured without revealing the key.

## Validate

```bash
npm test
npm run build
```

Before using production payloads, remove or mask customer identifiers and personal data.
