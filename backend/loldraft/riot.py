from __future__ import annotations

import random
import threading
import time
from collections import Counter, deque
from itertools import zip_longest
from urllib.parse import quote

import httpx

from .config import REGIONS, cutoff_ts, now_ts
from .ingestion import InvalidMatch, normalize


class RiotError(RuntimeError):
    """A deliberately sanitized message; credentials and raw responses are never logged."""


class CollectionCancelled(RiotError):
    pass


class RiotClient:
    def __init__(self, key, *, client=None, stop=None, progress=None, throttle=True):
        if not key:
            raise RiotError("RIOT_API_KEY is missing. Set it in the local .env file.")
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.key = key
        self.stop = stop or threading.Event()
        self.progress = progress or (lambda _: None)
        self.throttle = throttle
        self.calls = {}
        self.limits = {}  # Dynamic per-routing application limits.

    def close(self):
        self.client.close()

    def pause(self, seconds):
        if self.stop.wait(seconds):
            raise CollectionCancelled("Collection stopped; progress has been saved.")

    def request(self, host, path, params=None):
        if host not in set(REGIONS.values()) | {r.lower() for r in REGIONS}:
            raise RiotError("Unrecognized Riot host")
        if not path.startswith("/lol/") and not path.startswith("/riot/account/"):
            raise RiotError("Unrecognized Riot endpoint")
        for attempt in range(7):
            if self.stop.is_set():
                raise CollectionCancelled("Collection stopped; progress has been saved.")
            if self.throttle:
                calls = self.calls.setdefault(host, deque())
                limits = self.limits.get(host, [(100, 120), (20, 1)])
                longest = max(period for _, period in limits)
                t = time.monotonic()
                while calls and calls[0] < t - longest:
                    calls.popleft()
                for count, period in limits:
                    window = [c for c in calls if c > t - period]
                    if len(window) >= count:
                        self.pause(max(0, window[-count] + period - t) + 0.1)
                        t = time.monotonic()
                calls.append(time.monotonic())
            try:
                response = self.client.get(
                    f"https://{host}.api.riotgames.com{path}",
                    params=params, headers={"X-Riot-Token": self.key},
                )
            except httpx.RequestError:
                if attempt == 6:
                    raise RiotError("Riot API network failure; pending downloads are saved.") from None
                self.progress("Network interrupted; retrying with backoff")
                self.pause(min(60, 2 ** attempt))
                continue
            limits = response.headers.get("X-App-Rate-Limit", "")
            if limits:
                try:
                    self.limits[host] = [tuple(map(int, item.split(":"))) for item in limits.split(",")]
                except ValueError:
                    pass
            if response.status_code in (401, 403):
                raise RiotError("Riot key expired, invalid, or not authorized. Update .env and resume collection.")
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                try:
                    delay = max(1, float(response.headers.get("Retry-After", "120")))
                except ValueError:
                    delay = 120
                self.progress(f"Riot rate limit; waiting {delay:.0f}s. Progress is saved.")
                self.pause(delay + 0.1)
                continue
            if response.status_code >= 500:
                self.pause(min(60, 2 ** attempt) + random.random())
                continue
            if response.status_code != 200:
                raise RiotError(f"Riot API returned HTTP {response.status_code}; no response body retained.")
            try:
                return response.json()
            except ValueError:
                raise RiotError("Riot API returned malformed JSON") from None
        raise RiotError("Riot API retries exhausted; resume to continue pending downloads.")

    def seed_players(self, region, queue, tiers):
        host = region.lower()
        queue_name = "RANKED_SOLO_5x5" if queue == 420 else "RANKED_FLEX_SR"
        # Reproducible round-robin tier sampling. This is a seed-rank cohort, not historic match rank.
        for page in range(1, 101):
            found = False
            cohorts = []
            for tier in tiers:
                if tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
                    if page != 1:
                        continue
                    response = self.request(host, f"/lol/league/v4/{tier.lower()}leagues/by-queue/{queue_name}")
                    entries = (response or {}).get("entries", [])
                else:
                    division = ("I", "II", "III", "IV")[(page - 1) % 4]
                    page_number = (page - 1) // 4 + 1
                    entries = self.request(host, f"/lol/league/v4/entries/{queue_name}/{tier}/{division}", {"page": page_number}) or []
                players = []
                for entry in entries:
                    puuid = entry.get("puuid")
                    # Legacy League-V4 may return only encrypted summonerId.
                    if not puuid and entry.get("summonerId"):
                        summoner = self.request(host, "/lol/summoner/v4/summoners/" + quote(entry["summonerId"], safe=""))
                        puuid = (summoner or {}).get("puuid")
                    if puuid:
                        players.append(puuid)
                random.Random(page * 31 + len(tier)).shuffle(players)
                found |= bool(players)
                cohorts.append([(puuid, tier) for puuid in players])
            for batch in zip_longest(*cohorts):
                for item in batch:
                    if item is not None:
                        yield item
            if not found:
                return


def collect(store, settings, key, *, stop=None, progress=None, client=None):
    progress = progress or (lambda _: None)
    stop = stop or threading.Event()
    api = RiotClient(key, client=client, stop=stop, progress=progress)
    routing = REGIONS[settings.region]
    counts = Counter(imported=0, duplicate=0, rejected=0)
    initial = store.stats(settings.region, settings.queue, settings.patches)["matches"]
    scope_total = initial
    counted_at = time.monotonic()
    discovery_scope = {"region": settings.region, "queue": settings.queue, "tiers": sorted(settings.tiers)}
    cursor = store.get_meta("discovery", {})
    if (cursor.get("scope") != discovery_scope or cursor.get("completed") or
            now_ts() - cursor.get("cycle_started_at", 0) >= 86400):
        cursor = {"scope": discovery_scope, "seeds_completed": 0, "cycle_started_at": now_ts()}
    # A traversal ordinal is persisted, never a PUUID, player name, or hash of an identity.
    completed_seeds = cursor.get("seeds_completed", 0)
    # Pending IDs persist; seed identities only live in memory and never originate from the local draft.
    def drain():
        nonlocal scope_total, counted_at
        for match_id in store.pending(settings.region):
            raw = api.request(routing, "/lol/match/v5/matches/" + quote(match_id, safe=""))
            if raw is None:
                store.downloaded(match_id, "rejected", "Unavailable from Riot")
                counts["rejected"] += 1
                continue
            try:
                match = normalize(raw, region=settings.region)
                inserted = store.insert(match)
                counts["imported" if inserted else "duplicate"] += 1
                if inserted and match["queue"] == settings.queue and (not settings.patches or match["patch"] in settings.patches):
                    scope_total += 1
                store.downloaded(match_id)
                store.set_meta("last_refresh", now_ts())
            except InvalidMatch as exc:
                counts["rejected"] += 1
                store.downloaded(match_id, "rejected", str(exc))
            if time.monotonic() - counted_at > 60 or scope_total >= settings.target_matches:
                scope_total = store.stats(settings.region, settings.queue, settings.patches)["matches"]
                counted_at = time.monotonic()
            total = scope_total
            if total % 10 == 0 or total == initial + 1:
                progress(f"{total:,} / {settings.target_matches:,} recent matches; {counts['rejected']:,} excluded")
            if total >= settings.target_matches:
                return True
        return False
    try:
        if initial >= settings.target_matches:
            return dict(counts)
        progress(f"Resuming saved downloads; {initial:,} eligible recent matches")
        while store.pending(settings.region):
            if drain():
                return dict(counts)
        seen = set()
        for ordinal, (puuid, tier) in enumerate(api.seed_players(settings.region, settings.queue, settings.tiers)):
            if ordinal < completed_seeds:
                continue
            if puuid in seen:
                cursor.update(seeds_completed=ordinal + 1, updated_at=now_ts())
                store.set_meta("discovery", cursor)
                continue
            seen.add(puuid)
            progress(f"Discovering last-30-day matches from {tier} ranked seed cohort")
            for start in range(0, 5000, 100):
                ids = api.request(routing, "/lol/match/v5/matches/by-puuid/" + quote(puuid, safe="") + "/ids",
                                  {"startTime": cutoff_ts(), "endTime": now_ts(), "queue": settings.queue,
                                   "start": start, "count": 100}) or []
                store.enqueue(i for i in ids if i.startswith(settings.region + "_"))
                while store.pending(settings.region):
                    if drain():
                        return dict(counts)
                if len(ids) < 100:
                    break
            cursor.update(seeds_completed=ordinal + 1, updated_at=now_ts())
            store.set_meta("discovery", cursor)
        cursor.update(completed=True, updated_at=now_ts())
        store.set_meta("discovery", cursor)
        progress("Seed cohort exhausted; add tiers or resume with refreshed ladder entries")
        return dict(counts)
    finally:
        api.close()
