from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .config import REGIONS, ROLES, cutoff_ts, now_ts


class InvalidMatch(ValueError):
    pass


def normalize(raw: dict, *, region=None, queue=None, patches=None) -> dict:
    """Extract a minimal public composition; reject anything outside the last 30 days."""
    try:
        info = raw["info"]
        match_id = raw["metadata"]["matchId"]
        platform = match_id.split("_")[0].upper()
        if platform not in REGIONS or not re.fullmatch(r"[A-Z0-9]+_\d+", match_id):
            raise InvalidMatch("Invalid platform or match ID")
        started = int(info.get("gameStartTimestamp") or info.get("gameCreation", 0)) // 1000
        if not cutoff_ts() <= started <= now_ts():
            raise InvalidMatch("Outside the strict rolling 30-day window")
        version = str(info["gameVersion"])
        patch = ".".join(version.split(".")[:2])
        if not re.fullmatch(r"\d+\.\d+", patch):
            raise InvalidMatch("Missing patch version")
        q = int(info["queueId"])
        duration = int(info["gameDuration"])
        if q not in (420, 440) or int(info.get("mapId", 0)) != 11 or info.get("gameMode") != "CLASSIC":
            raise InvalidMatch("Only ranked Summoner's Rift is supported")
        if info.get("gameType", "MATCHED_GAME") != "MATCHED_GAME" or duration < 600:
            raise InvalidMatch("Remade, too short, or unsuitable match")
        if region and platform != region or queue and q != queue or patches and patch not in patches:
            raise InvalidMatch("Outside selected region, queue, or patches")
        participants = info["participants"]
        if len(participants) != 10 or any(p.get("gameEndedInEarlySurrender", False) for p in participants):
            raise InvalidMatch("Incomplete or remade match")
        teams = {100: [], 200: []}
        wins = {100: set(), 200: set()}
        for p in participants:
            team = int(p["teamId"])
            champ = int(p["championId"])
            if team not in teams or not 0 < champ < 10000 or not isinstance(p["win"], bool):
                raise InvalidMatch("Invalid team, champion, or outcome")
            role = p.get("teamPosition", "")
            teams[team].append({"champion_id": champ, "role": role if role in ROLES else ""})
            wins[team].add(p["win"])
        ids = [p["champion_id"] for team in teams.values() for p in team]
        if any(len(t) != 5 for t in teams.values()) or len(set(ids)) != 10:
            raise InvalidMatch("Invalid ranked composition")
        if len(wins[100]) != 1 or len(wins[200]) != 1 or wins[100] == wins[200]:
            raise InvalidMatch("Inconsistent match outcomes")
        for team in teams.values():
            counts = Counter(p["role"] for p in team if p["role"])
            for p in team:
                if counts[p["role"]] > 1:
                    p["role"] = ""  # Ambiguous roles are unknown, never guessed.
        return {"match_id": match_id, "started_at": started, "patch": patch,
                "region": platform, "queue": q, "duration": duration,
                "blue_win": next(iter(wins[100])), "blue": teams[100], "red": teams[200]}
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InvalidMatch):
            raise
        raise InvalidMatch("Malformed Match-V5 record") from None


def import_file(path: Path, store, *, region=None, queue=None, patches=None, progress=None):
    """Match-V5 JSON, a JSON array, or streaming JSONL. Raw records are never retained."""
    counts = Counter(imported=0, duplicate=0, rejected=0)
    reasons = Counter()
    with Path(path).open(encoding="utf-8-sig") as stream:
        first = stream.read(1)
        while first.isspace():
            first = stream.read(1)
        stream.seek(0)
        if first == "[":
            records = iter(json.load(stream))
        elif Path(path).suffix.lower() == ".json":
            records = iter([json.load(stream)])
        else:
            records = (line for line in stream if line.strip())
        for i, record in enumerate(records):
            try:
                raw = json.loads(record) if isinstance(record, str) else record
                match = normalize(raw, region=region, queue=queue, patches=patches)
                counts["imported" if store.insert(match) else "duplicate"] += 1
            except (InvalidMatch, json.JSONDecodeError) as exc:
                counts["rejected"] += 1
                reasons[str(exc)[:120]] += 1
            if progress and i % 500 == 0:
                progress(f"Processed {i + 1:,} records; {counts['imported']:,} new recent matches")
    store.set_meta("last_refresh", now_ts())
    return {**counts, "reasons": dict(reasons)}
