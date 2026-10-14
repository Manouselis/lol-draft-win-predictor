# Security review — 14 October 2026

Scope: source and reachable Git history, backend credential/network boundaries,
local setup workflow, dependency advisories, GitHub secret alerts, and Windows/source
distribution artifacts. Checks are point-in-time observations, not a guarantee.

## Findings and changes

- A redirected Windows LOCALAPPDATA folder could select an empty profile. The app
  now reuses an existing user profile when the redirected location has no .env.
  The desktop launcher pins the resolved private file for child processes and key
  renewal. Settings displays the actual database and configuration paths.
- Upgraded Vitest from 3.2.7 to 4.1.11, removing advisories affecting Vitest's mock
  redirect handling and its Tinypool dependency. The refreshed frontend audit reports
  zero known advisories; the pinned Python requirement audit also reports none.
- Added a local credential form with a per-process request token, strict JSON/origin
  checks, redacted validation failures, fixed Riot HTTPS validation, atomic private
  writes, and no response echo or browser persistence.
- Added CSP and frame protections. A production HTTP request cannot use the test-only
  testserver host allowance. Malformed Origin ports fail closed.
- Added staged/history Git guards and CI scans for Riot keys and private artifacts.
  GitHub native secret scanning and push protection were verified enabled; the open
  secret-alert count was zero at review time.
- The Windows launcher verifies the downloaded runtime ZIP against a pinned SHA-256.
  The distribution resource allowlist excludes local keys, databases and models.

See [SECURITY.md](../SECURITY.md) for limitations and reporting. Dependency data and
remote repository settings can change; CI reruns checks on subsequent pushes.

## Sources

- [Vitest advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)
- [Tinypool worker-options advisory](https://github.com/advisories/GHSA-5gmw-xhrv-c9v3)
- [Tinypool run-options advisory](https://github.com/advisories/GHSA-85c8-ppgw-ccpr)
- [GitHub large-file/database guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
