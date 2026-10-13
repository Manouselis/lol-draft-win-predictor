# Riot policy review and integration status

Reviewed against official sources on **13 October 2026**. Policies can change; recheck before distribution or live use.

## Sources

- [General developer policies](https://developer.riotgames.com/policies/general): product registration/audit, supported data services, game integrity, required disclaimer, security.
- [League of Legends documentation](https://developer.riotgames.com/docs/lol): approved/unapproved use cases, registration, routing, Data Dragon, the unsupported League Client API.
- [Developer portal documentation](https://developer.riotgames.com/docs/portal): key types, application process, limits, HTTP errors.
- [Official API reference](https://developer.riotgames.com/apis/): Match-V5, League-V4, Summoner-V4.
- [API terms](https://developer.riotgames.com/terms): terms applicable to Riot developer tools and data.

## What is established and what is uncertain

Riot documents the League Client API as unsupported and asks developers to register their product and describe which client endpoints they use. Riot does not guarantee documentation, uptime, backward compatibility, or support for it.

The League documentation's unapproved-use-case section restricts products providing game-session-specific information previously unknown to the player. It also restricts dictating decisions and analyzing players deliberately hidden by the game. The general policies prohibit unfair advantage and require product registration and auditing.

**Our interpretation:** a live, session-specific estimated win probability needs explicit Riot review; using only visible champions does not by itself prove that the derived prediction is permitted. We do not claim that the policy explicitly names this predictor or that Riot has approved it. The shipped build disables the local adapter and live display until external authorization is obtained. Manual mode is intended for offline hypothetical composition research. Do not use it to bypass a live-use restriction.

An API key authorizes requests within its scope. It does not authorize every proposed product feature. A public source repository is not a public production service or Riot endorsement. This source release does not include a key, match dataset, trained model, or player information.

## Register/review the product

1. Sign in at the [Riot Developer Portal](https://developer.riotgames.com/) using your own account.
2. Register a product. Describe offline draft research, recent Match-V5 ingestion, masked training, aggregate outcome statistics, and the proposed local client integration.
3. Provide this repository, screenshots or a runnable build, and a user flow that shows unknown picks and visible information only.
4. Explicitly ask whether showing a **live champion-select win probability** for a visible composition is allowed. List the sole client endpoint: read-only `GET /lol-champ-select/v1/session` on loopback.
5. Document that no player identities, scouting, memory access, packet capture, game actions, selection, locking, or anti-cheat workaround is involved.
6. Request the appropriate personal key for a permitted personal product or a production key if you intend to distribute a registered service. Development keys are temporary and development-only; do not distribute one.
7. Keep the product description current and seek review of changed features. Follow Riot's response. Do not enable a disallowed feature by toggling a setting.

Registration is an account action for the owner; this app does not submit an application, accept terms, obtain keys, or claim approval on your behalf.

## Technical boundaries

- Official Match-V5 via HTTPS with header-based credentials; no unauthorized scraping.
- Riot Data Dragon supplies static champion IDs/names/portraits; no strength formulas.
- Fixed loopback LCU host; a GET allowlist with one endpoint; no redirects or game writes.
- Lockfile credential represented as a redacted object; never returned by HTTP or stored in SQLite.
- No hidden PUUIDs or Riot IDs extracted from session data; enemy intention/hover fields are ignored.
- Rate-limit handling and persistent download IDs; expired keys stop cleanly.
- No automatic client access until both live configuration flags are enabled following external approval.
- Required Riot disclaimer appears in the interface footer and README.
