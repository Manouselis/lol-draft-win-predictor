"""Local credential setup. No credential is returned, logged, or sent to another host."""
from __future__ import annotations

import os
import re
import tempfile

import httpx

from .config import REGIONS


def validate_key(key, region, *, client=None):
    if not re.fullmatch(r"RGAPI-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", key):
        raise ValueError("Enter the complete development or personal API key from Riot's portal.")
    if region not in REGIONS:
        raise ValueError("Choose a supported Riot platform first.")
    owned = client is None
    client = client or httpx.Client(timeout=15, follow_redirects=False)
    try:
        response = client.get(f"https://{region.lower()}.api.riotgames.com/lol/status/v4/platform-data",
                              headers={"X-Riot-Token": key})
        if response.status_code in (401, 403):
            raise ValueError("Riot rejected this key. Renew it in the developer portal, then try again.")
        if response.status_code != 200:
            raise ValueError("Riot could not validate the key right now. Try again shortly.")
    except httpx.RequestError:
        raise ValueError("Could not reach Riot. Check your Internet connection and try again.") from None
    finally:
        if owned:
            client.close()


def save_key(config, key):
    """Replace only the key, atomically, in the resolved private configuration file."""
    if config.env_file is None:
        raise ValueError("The launcher has not selected a local configuration file.")
    path = config.env_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    lines = [line for line in lines if not re.match(r"\s*RIOT_API_KEY\s*=", line)]
    lines.append("RIOT_API_KEY=" + key)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".env.", suffix=".tmp", delete=False) as output:
            temporary = output.name
            os.chmod(temporary, 0o600)
            output.write("\n".join(lines) + "\n")
        os.replace(temporary, path)
        temporary = None
        config.riot_key = key
    finally:
        if temporary:
            os.unlink(temporary)
