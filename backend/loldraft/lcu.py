from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import ROLES
from .schemas import Draft, Pick

ENDPOINT = "/lol-champ-select/v1/session"


@dataclass(repr=False)
class Credentials:
    port: int
    password: str = field(repr=False)

    def __repr__(self):
        return "Credentials(<redacted>)"


def parse_lockfile(text):
    parts = text.strip().split(":")
    if len(parts) != 5 or parts[0] != "LeagueClient" or parts[4] != "https":
        raise ValueError("Invalid League lockfile")
    port = int(parts[2])
    if not 1024 <= port <= 65535 or not parts[3]:
        raise ValueError("Invalid League connection details")
    return Credentials(port, parts[3])


def discover(directory=""):
    # No process command-line inspection, memory reading, recursive disk scan, or remote host.
    locations = [Path(directory)] if directory else []
    if os.name == "nt":
        locations += [Path("C:/Riot Games/League of Legends"), Path("D:/Riot Games/League of Legends"),
                      Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Riot Games/League of Legends"]
    elif os.uname().sysname == "Darwin":
        locations.append(Path("/Applications/League of Legends.app/Contents/LoL"))
    for path in locations:
        try:
            return parse_lockfile((path / "lockfile").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def parse_session(session, *, region="EUW1", queue=420):
    """Conservative visible-only parsing. Never return any player identifier."""
    actions = [a for group in session.get("actions", []) for a in group if a.get("type") == "pick"]
    by_cell = {a.get("actorCellId"): a for a in actions}
    def parse_team(name, enemy=False):
        result = []
        for player in session.get(name, [])[:5]:
            action = by_cell.get(player.get("cellId"), {})
            champion = int(player.get("championId") or 0)
            completed = action.get("completed") is True and action.get("championId") == champion and champion > 0
            if enemy:
                # Never inspect enemy intents or incomplete enemy actions. Both visible evidence fields must agree.
                result.append(Pick(champion_id=champion, state="locked") if completed else Pick())
                continue
            role = str(player.get("assignedPosition", "")).upper()
            role = role if role in ROLES else ""
            if completed:
                result.append(Pick(champion_id=champion, state="locked", role=role))
            else:
                intent = int(player.get("championPickIntent") or champion or action.get("championId") or 0)
                result.append(Pick(champion_id=intent, state="hover" if intent else "unknown", role=role))
        return result + [Pick() for _ in range(5 - len(result))]
    side = "unknown"
    team_id = session.get("myTeamId")
    if team_id not in (100, 200):
        explicit = {p.get("teamId") for p in session.get("myTeam", []) if p.get("teamId") in (100, 200)}
        team_id = next(iter(explicit)) if len(explicit) == 1 else None
    if team_id in (100, 200):
        side = "blue" if team_id == 100 else "red"
    return Draft(allies=parse_team("myTeam"), enemies=parse_team("theirTeam", enemy=True),
                 side=side, region=region, queue=queue)


class LcuMonitor:
    def __init__(self, config, update, *, discover_fn=None, client_factory=None):
        self.config = config
        self.update = update
        self.find = discover_fn or (lambda: discover(config.lcu_directory))
        self.client_factory = client_factory or httpx.AsyncClient
        self.status = "disabled"
        self.message = "Live integration awaits Riot review; use manual analysis."
        self.available = False
        self.session_id = None

    async def once(self):
        creds = self.find()
        self.available = creds is not None
        if not self.config.lcu_enabled or not self.config.riot_live_approved:
            self.status = "disabled"
            self.message = "League detected; live mode awaits Riot review." if creds else "Live mode disabled; manual analysis is available."
            return None
        if creds is None:
            self.status = "disconnected"
            self.message = "League client unavailable. Reconnecting automatically."
            self.session_id = None
            self.update(None, reset=True)
            return None
        try:
            async with self.client_factory(
                base_url=f"https://127.0.0.1:{creds.port}", auth=("riot", creds.password),
                verify=self.config.lcu_ca_file or False, timeout=1.5, trust_env=False,
                follow_redirects=False,
            ) as client:
                # The self-signed certificate exception applies ONLY to this fixed loopback endpoint.
                response = await client.get(ENDPOINT)
            if response.status_code == 404:
                self.status, self.message = "connected", "League connected; waiting for champion select."
                self.session_id = None
                self.update(None, reset=True)
                return None
            if response.status_code != 200:
                raise ValueError("Client unavailable")
            data = response.json()
            draft = parse_session(data, region=self.config.region, queue=self.config.queue)
            # gameId distinguishes consecutive drafts. Only a nonidentifying lobby ID is retained in RAM.
            identity = str(data.get("gameId", ""))
            reset = bool(identity and identity != self.session_id)
            self.session_id = identity
            self.status, self.message = "connected", "Read-only champion select connected."
            self.update(draft, reset=reset)
            return draft
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self.status, self.message = "disconnected", "League restarted or session unavailable. Reconnecting automatically."
            self.session_id = None
            self.update(None, reset=True)
            return None

    async def run(self):
        while True:
            await self.once()
            await asyncio.sleep(.5 if self.status == "connected" else 1)
