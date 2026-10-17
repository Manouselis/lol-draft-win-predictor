# Raspberry Pi 5 collection host

The Pi runs the historical collector independently of the Windows laptop. It starts
at boot, waits for network clock synchronization, preserves pending downloads, and
retries after interruptions. It does not run League, expose a web server, or train
models. The Windows application can train from a consistent Pi database snapshot.

## Hardware and first boot

Use a separate Pi 5 power supply (the official 27 W USB-C model is recommended),
a microSD card (32 GB or larger leaves room for the OS and dataset), a card reader,
and an Internet connection. Ethernet to the router is convenient; Wi-Fi works too.
Power from the laptop is unsuitable when the goal is to keep collecting with the
laptop switched off. A bare board connected by USB is not an installed computer.

Use [official Raspberry Pi Imager](https://www.raspberrypi.com/software/) to install
**Raspberry Pi OS Lite (64-bit)** on the identified microSD card. Set hostname
`league-draft-pi`, a normal user such as `draftlab`, network details if using Wi-Fi,
and SSH access. Enter your OS password yourself; prefer SSH public-key access from
the laptop. Imager erases the selected card, so identify the removable card before
writing. A monitor and keyboard are not required for this headless setup.

Move the card into the Pi, connect Ethernet if used, and power it from the wall
supply. See [Raspberry Pi's first-boot instructions](https://www.raspberrypi.com/documentation/computers/getting-started.html).

## Install the collector

Once SSH works, run on the Pi as its normal user:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Manouselis/lol-draft-win-predictor.git
cd lol-draft-win-predictor
bash scripts/pi/install.sh
```

The installer requires Linux ARM64, installs only the small collection dependencies,
creates a private profile, and enables `league-draft-collector.service` for boot.
It does not flash storage, transfer a key, start collection, or change firewall/router
settings. Finish the database/key transfer before starting it or rebooting.

Files on the Pi:

- `~/lol-draft-win-predictor/data/matches.sqlite3`: authoritative match database,
  pending IDs, scope and discovery position; Git-ignored.
- `~/.local/state/LeagueDraftLab/.env`: private key/configuration, mode 600, outside
  the repo. If XDG_STATE_HOME is configured, the profile is under that location.
- Logs: `journalctl -u league-draft-collector.service`.

## Move the existing dataset

Keep the laptop collecting until the Pi has booted and the service is installed.
Then stop laptop collection with **Stop & save progress**, and wait for it to stop.
Only one machine should collect with the same key; separate machines do not share
the local process lock or coordinate Riot's rate limits.

Create a snapshot in the existing Windows source checkout (which has Python installed):

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe scripts\pi\collector.py --data-dir "$PWD\data" backup --output "$PWD\data\pi-transfer\matches.sqlite3"
```

This uses SQLite's backup API, includes committed WAL changes, checks integrity,
and refuses to overwrite an existing snapshot. Keep the original database as a
backup. For a repeated attempt, choose a new output directory.

Create an incoming directory on the Pi and transfer **only the snapshot** over SSH:

```powershell
ssh draftlab@league-draft-pi.local 'mkdir -p ~/lol-draft-win-predictor/data/incoming'
scp .\data\pi-transfer\matches.sqlite3 draftlab@league-draft-pi.local:~/lol-draft-win-predictor/data/incoming/matches.sqlite3
```

Use your actual Pi username. Verify the SSH host identity on first connection.
On the Pi, before starting the collector or running `status`/`key` for the first time:

```bash
cd ~/lol-draft-win-predictor
.collector-venv/bin/python scripts/pi/collector.py --data-dir data/incoming backup --output data/matches.sqlite3
```

If the destination database already exists, stop and preserve it; the command
refuses to replace it. Existing databases need a reviewed merge rather than an
overwrite. Never use OneDrive or a shared network filesystem for the live Pi SQLite
database; transfer consistent snapshots over SSH instead.

## Key, startup and monitoring

On the Pi:

```bash
.collector-venv/bin/python scripts/pi/collector.py key
sudo systemctl start league-draft-collector.service
sudo systemctl status league-draft-collector.service --no-pager
.collector-venv/bin/python scripts/pi/collector.py status
journalctl -u league-draft-collector.service -n 30 --no-pager
```

The `key` command hides input, validates with Riot, and writes only the private
profile. Do not copy the Windows `.env` wholesale: its paths are Windows-specific.
Do not put keys in command arguments, Git or shared logs. The deployment can also
transfer the key privately over an authenticated SSH connection to your confirmed Pi.

Service behavior:

- No laptop or interactive login is needed after boot.
- Requests follow Riot limits and the strict rolling 30-day filter.
- A synchronized network clock is required before collection starts.
- Network errors, a completed target, or a rejected key cause a retry after five
  minutes. Successful completion is retried so aging records can be replenished.
- `sudo systemctl stop league-draft-collector.service` stops it safely and does not
  automatically restart it. `start` resumes; `disable --now` disables boot startup.
- No training is performed on the Pi. Use a database snapshot for laptop training.

**A Pi does not extend a Riot key's lifetime.** Development keys still need renewal.
Run the private `key` command with the renewed value and then:

```bash
sudo systemctl restart league-draft-collector.service
```

Changing the key in the laptop's Settings does not update the Pi automatically.
A suitable longer-lived Riot key requires the appropriate Riot approval.

## Copy collected data back

On the Pi, create a fresh snapshot in its ignored `data/` folder:

```bash
.collector-venv/bin/python scripts/pi/collector.py backup --output data/laptop-snapshot.sqlite3
```

Copy that snapshot over SSH. Stop any laptop collector before importing or merging
it. Keep both originals and use a reviewed restore/merge so newer local data is not
lost. Do not copy a live SQLite file or just its main file while WAL writes continue.

## Verification boundaries

The collector-only dependency path, Windows snapshot/privacy checks, Linux SIGTERM
handling and systemd syntax are exercised in tests/CI. ARM64 wheels are checked
separately. Those checks do not prove that an unbooted board is configured: final
verification requires SSH access, an actual Pi reboot and increasing match counts
while the laptop collector is stopped. Live League approval remains separate.
