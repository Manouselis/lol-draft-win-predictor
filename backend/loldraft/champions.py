from __future__ import annotations

import json
from pathlib import Path

import httpx


def parse_catalog(raw, version):
    champions = []
    for item in raw.get("data", {}).values():
        champion_id = int(item["key"])
        champions.append({"id": champion_id, "name": item["name"], "slug": item["id"],
                          "tags": item.get("tags", []),
                          "portrait": f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{item['id']}.png"})
    return {"version": version, "champions": sorted(champions, key=lambda c: c["name"])}


def catalog(directory: Path, *, refresh=False, client=None):
    path = directory / "champions.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        with client or httpx.Client(timeout=15) as api:
            response = api.get("https://ddragon.leagueoflegends.com/api/versions.json")
            response.raise_for_status()
            version = response.json()[0]
            response = api.get(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json")
            response.raise_for_status()
            result = parse_catalog(response.json(), version)
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")
        return result
    except (httpx.HTTPError, ValueError, KeyError):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        # Real static data may be unavailable; IDs can still be entered, never invent a mapping.
        return {"version": None, "champions": [], "error": "Data Dragon unavailable; retry champion refresh."}
