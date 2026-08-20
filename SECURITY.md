# Security policy

Security fixes are applied to the latest version on the default branch.

Use GitHub's **Report a vulnerability** private security advisory flow. Do not open a public issue for suspected credential exposure, injection, authentication, privacy, or data-access vulnerabilities.

Keep Google credentials outside the repository, use Application Default Credentials, query the minimum required range, retain the billing guard, and never add raw component values or unhashed identifiers to the application payload. Keep `GEMINI_API_KEY` in Cloudflare Worker secrets and never expose it through a `VITE_` variable.
