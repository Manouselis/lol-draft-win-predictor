# League Draft Lab

A local Windows-friendly League of Legends composition research app: Python, SQLite, scikit-learn, FastAPI, React, TypeScript, Vite, and Tailwind. It includes manual champion selection, tentative versus confirmed estimates, draft progression, data management, and a read-only League Client adapter.

**Probabilities require real historical matches. There are no bundled strength scores, fabricated win percentages, or synthetic historical datasets.** Until enough eligible data is collected and a model is trained, the UI says **Model not ready**. All collection, import, and training enforce a maximum age of **30 days**, as required for this project.

The automatic integration is disabled pending Riot review of this specific use case. Use manual mode for offline composition analysis and fixture replay for integration testing. A valid developer key is API authentication, not Riot approval of the product or live predictions. See [compliance](docs/compliance.md).

## Start the installed application

From PowerShell in this project directory:

```powershell
.\.venv\Scripts\python.exe -m loldraft.cli serve
```

Open **http://127.0.0.1:8765**. The built frontend is served by the Python process; a separate frontend server is not needed. `Ctrl+C` stops the foreground server.

Double-click **Start.cmd** to launch the same service and open the browser. Existing server instances are reused. The local service binds only to `127.0.0.1`. There is no cloud deployment or paid service.

In a second PowerShell window, start or resume collection:

```powershell
.\.venv\Scripts\python.exe -m loldraft.cli collect --auto-train
```

The collector saves match IDs and validated composition records continuously. It trains automatically once the 50,000-match floor is met, and again after each additional 25,000 eligible matches. The target is **100,000 unique matches**. The UI can also start/stop collection, import data, and train. Collection has an OS lock, so two processes cannot spend the same key's quota concurrently.

## Fresh installation

Requirements: Python 3.11 or newer (3.12 tested), Node.js 22 or newer, pnpm 11, and Git. Tested on Windows 10/11; the backend uses portable Python and SQLite. macOS lockfile discovery is included but has not been exercised on macOS. League of Legends does not have an official Linux client.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
pnpm install --frozen-lockfile
pnpm --filter league-draft-lab-ui build
Copy-Item .env.example .env
```

Edit `.env` locally to set `RIOT_API_KEY`. Do not put a key in a frontend variable, a URL, an issue, a commit, a screenshot, or a shared log. `.env`, databases, client lockfiles, models, and logs are ignored by Git. The Python lockfile records the versions tested on this machine; `pyproject.toml` gives compatible dependency ranges for other environments.

Development:

```powershell
# Terminal 1
.\.venv\Scripts\python.exe -m loldraft.cli serve
# Terminal 2
pnpm --filter league-draft-lab-ui dev
```

The Vite frontend at http://127.0.0.1:5173 proxies `/api` to the loopback Python service.

## Data: real, recent, and resumable

Default scope: **EUW1**, **ranked solo/duo queue 420**, **Summoner's Rift**, with Silver/Gold/Platinum/Emerald ladder seed cohorts. Queue 440 and other Riot platforms are configurable. Unsupported/custom/ARAM games, games shorter than 10 minutes, flagged remakes, inconsistent teams/outcomes, duplicate champions, missing timestamps, future timestamps, and games older than 30 days are rejected.

The official pipeline uses:

- League-V4 ranked entries to discover public ranked cohorts. PUUIDs live in memory only.
- Match-V5 match ID lists, with `queue`, `startTime`, `endTime`, and pagination.
- Match-V5 match details to extract only ID, timestamp, version/patch, queue, platform, duration, champion IDs, team, role where available, and win outcome.

No summoner names, Riot IDs, PUUIDs, raw API payloads, client passwords, or player telemetry are stored in the match database. Rank filters select **current ladder seed cohorts**; they do not establish historical participant rank at match time. Cohort sampling may differ from the entire ranked population. Collection is independent of the local live draft and performs no scouting.

Downloads use application limits reported in Riot response headers, separately per routing host. `429 Retry-After` is honored; network/5xx errors back off; 401/403 stop with a safe message. Redirects are disabled. Interrupted IDs stay pending in SQLite. Keys are passed only in the `X-Riot-Token` header to allowlisted official HTTPS hosts.

At the development key's **100 requests per two minutes**, 100,000 match-detail calls alone require at least **33 hours 20 minutes**. Discovery, unavailable records, latency, and retries add time. A 24-hour development key cannot complete that target in one validity window. Renew the key in Riot's portal, update the local `.env`, then resume. The app reads the renewed key when a new collection job starts; it does not generate keys or solve CAPTCHAs. Applying for an appropriate personal/production key is documented in [compliance](docs/compliance.md).

### Import legally obtained historical matches

Supported: one official Match-V5 JSON response, a JSON array of responses, or streaming JSONL/NDJSON with one response per line. Dates must still be in the last 30 days. This intentionally rejects older public datasets, datasets without reliable match dates, and aggregate CSVs without full champion IDs and outcomes.

```powershell
.\.venv\Scripts\python.exe -m loldraft.cli import "C:\path\recent-matches.jsonl"
.\.venv\Scripts\python.exe -m loldraft.cli status
.\.venv\Scripts\python.exe -m loldraft.cli train
```

The UI import accepts files up to 2 GiB. Use the streaming CLI for larger JSONL files. A JSON array is loaded into memory; JSONL is preferable for large datasets. Imported raw uploads are deleted after processing. Verify your right to use third-party datasets yourself; a code license is not a license for associated match data. Historical records that age out are excluded immediately, regardless of what remains in local storage.

## The statistical model

See [model card](docs/model-card.md) for method, assumptions, uncertainty, and limitations.

- An L2 regularized logistic regression learns champions, signed allied pairs, opposing matchups, three-champion combinations, roles when supplied, patch, and patch/champion interactions. Feature hashing bounds memory; rare interactions below 20 training occurrences are omitted. Separate region/queue models avoid pooling incompatible populations.
- Eight masked drafts per training match include empty, complete, and randomly sampled independent 0–5 champion subsets on each team. No inference-time champion imputation takes place. One match's total sample weight is divided between its eight masks.
- A seven-day half-life weights recent outcomes more strongly. Patch changes are learned from outcomes on the patch, not hand-written strength scores or interpretations of patch notes.
- Deduplicated matches are split **by timestamp before augmentation** into 60% fit, 20% sigmoid calibration, and 20% final test. Identical timestamps cannot straddle split boundaries. The final test cohort never fits the estimator or calibrator.
- Empty drafts use the recency-weighted historical blue-side win baseline. Red-side estimates are oriented to the user's team. Unknown side uses an equal-side mixture and has no validated calibration interval.
- Evaluation reports **Brier score, log loss, calibration bins, and ECE** for 0, 2, 4, 6, 8, and 10 visible champions against the same historical baseline. The held-out data can show that champion select has little predictive value; poor comparisons are clearly flagged.
- The uncertainty band is a Wilson interval for outcomes within a held-out prediction bin at the nearest evaluated reveal count. It is **not an individual-match confidence interval**. Historical pair rates are descriptive associations, and displayed champion contributions are leave-one-visible-champion-out differences, not causal effects.
- Model artifacts and an `evaluation.json` report are saved locally, loaded automatically, versioned, and rejected if corrupt, incompatible, synthetic-labelled, outside region/queue, expired, or missing selected patch/champion support.

**50,000 eligible real matches is a readiness floor, not a statistical guarantee.** Training uses a 29-day subset to leave a one-day age margin; even that subset must meet the floor. Models expire when their oldest input becomes 30 days old. Refresh/retrain to keep predictions available. No real validation scores are claimed until an actual historical model is trained. Synthetic pipeline tests are not evidence of real-world predictive performance.

## League Client integration

The client adapter polls only `GET https://127.0.0.1:<port>/lol-champ-select/v1/session`, nominally every 500 ms. HTTP latency and client availability affect observed delay. It discovers a lockfile in known install directories or `LOL_LCU_DIRECTORY`, reads credentials in memory, reconnects after restarts, and clears stale drafts on disconnect or when champion select ends.

No process command-line scanning, memory access, injection, packet interception, hidden identities, enemy intents, champion selection, locking, or other game interaction is implemented. Enemy champions require a completed pick action **and** the matching visible team entry. Enemy hover/intention fields are ignored. An uncertain/absent side remains unknown; the adapter does not guess side from cell order.

The League Client API is **officially unsupported** and its session schema may change. The adapter is implemented and tested with synthetic session fixtures; a real client connection is not asserted by those tests. The local self-signed certificate exception is restricted to a fixed loopback HTTPS host; public Riot API TLS verification remains enabled. Configure `LOL_LCU_CA_FILE` to validate the local client against an appropriate CA when available.

Only after Riot has reviewed and permitted this exact use case:

```dotenv
LOL_RIOT_LIVE_APPROVED=true
LOL_LCU_ENABLED=true
LOL_LCU_DIRECTORY=C:\Riot Games\League of Legends
```

Restart the service and select **League client**. These settings record external authorization; they do not obtain it. The interface keeps connected/disconnected/manual status visible. Public GitHub source is not approval for distributing or deploying this application.

For offline integration testing, Settings → **Test synthetic draft replay** includes unknown → hover → hover replacement → lock → allied pair → visible enemy → full draft. The replay banner labels it synthetic. It does not train a synthetic model or add synthetic historical matches to the actual dataset.

## Tests and checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
pnpm --filter league-draft-lab-ui test
pnpm --filter league-draft-lab-ui build
```

Tests use explicitly synthetic fixtures in temporary directories. They cover normalization, date/queue/patch validation, champion mappings, deduplication, resumable IDs, temporal splitting, partial inference, empty baseline, blue/red complements, hover replacement/locking, hidden enemy fields, client restart/disconnect, expired/rate-limited/failing Riot requests, key renewal, model loading/expiry, and local API protections. No tests require a key or a running League client.

## Repository layout

```text
backend/loldraft/
  ingestion.py, riot.py, storage.py   # Official ingestion, whitelist, SQLite, deduplication
  features.py, model.py              # Masking, fitting, calibration, evaluation, inference
  lcu.py                            # Gated read-only client adapter
  api.py, runtime.py, cli.py         # Loopback service, SSE updates, jobs, command line
frontend/src/                       # Dark React interface, manual picker, charts, data/settings
tests/fixtures/                     # Synthetic champion-select sessions; no real player data
docs/                               # Compliance notes and model card
scripts/                            # Setup helpers
```

Source code is MIT licensed. Riot data, champion images, and trademarks retain their owners' rights and are subject to Riot's policies.

**League Draft Lab is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.**
