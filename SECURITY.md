# Security and private data

The app binds only to 127.0.0.1. Riot credentials are accepted through the local setup
screen, validated against a fixed official Riot HTTPS endpoint, and saved in the
resolved private AppData profile. They are never returned by the API or placed in
frontend assets, Git, model features, or match records. The browser input is masked
and is not saved in browser storage. Public API requests use header-based keys and
do not follow redirects. Local League credentials remain in memory only.

The key-save endpoint requires a per-process token, JSON content type, and the local
origin checks. Responses never echo validation inputs for that endpoint. The UI
cannot choose an arbitrary credential file path. The app also sends a restrictive
Content Security Policy, disallows framing, and checks loopback host names.

Raw JSON imports are processed in private profile temporary storage and deleted after
processing, so unfiltered player identifiers do not pass through the synced data folder.
Only whitelisted match facts enter the database. Quitting the background server also
requires the local request token and refuses to quit during active training.

Match data may live in the checkout's data/ directory. That directory, .env files,
models, logs, runtime downloads, and databases are Git-ignored. A cloud-synced
checkout can sync its local match data independently of Git. The key profile remains
outside the checkout. For sharing research data, prefer a separately reviewed,
versioned export rather than committing a changing SQLite database to Git history.

Install the local Git guards with:

    git config core.hooksPath .githooks

The pre-commit guard checks staged files. The pre-push guard checks all reachable
history. Both block Riot key patterns, common GitHub tokens, private keys and private
runtime artifacts without printing matched values. They require a Python interpreter
for developer commits. CI repeats the scan and audits Python/frontend dependencies.
GitHub's native secret scanning and push protection are an additional layer; they do
not replace the Riot-specific guard. Hooks and pattern matching can be bypassed or
miss unknown secret formats, so inspect the staged diff before pushing.

Desktop downloads use HTTPS and a SHA-256 digest pinned in the source launcher.
The Windows ZIP is built from an explicit resource list and is scanned before
publication. It contains no user configuration, real match dataset, or trained model.
The bundle is not code-signed; a digest confirms that it matches the published build,
not that software is free of every possible defect. Do not bypass Windows security
warnings to run an untrusted download.

Only load models generated locally. Joblib is executable serialization: placing an
untrusted model in the local data folder can execute code. No model-upload endpoint
is provided. This local tool is not a security boundary against malware or another
program already running as your Windows user.

To report a suspected leak, stop collection and revoke/renew the affected key through
Riot. Contact the repository owner privately; do not post credentials in a public
issue, screenshot, or log. No audit can guarantee zero risk.
