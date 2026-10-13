from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

REGIONS = {
    "EUW1": "europe", "EUN1": "europe", "TR1": "europe", "RU": "europe",
    "NA1": "americas", "BR1": "americas", "LA1": "americas", "LA2": "americas",
    "KR": "asia", "JP1": "asia", "OC1": "sea", "SG2": "sea",
    "TW2": "sea", "VN2": "sea", "PH2": "sea", "TH2": "sea",
}
TIERS = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER")
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
WINDOW_DAYS = 30  # User requirement: cannot be extended by a setting.


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def cutoff_ts() -> int:
    return now_ts() - WINDOW_DAYS * 86400


@dataclass
class Config:
    data_dir: Path
    region: str = "EUW1"
    queue: int = 420
    target_matches: int = 100_000
    min_matches: int = 50_000
    riot_key: str = field(default="", repr=False)
    lcu_enabled: bool = False
    riot_live_approved: bool = False
    lcu_directory: str = ""
    lcu_ca_file: str = ""

    @classmethod
    def load(cls):
        # Default state is outside OneDrive/Desktop source checkouts. Local .env remains a dev override.
        if os.name == "nt":
            state_dir = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local")) / "LeagueDraftLab"
        else:
            state_dir = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state")) / "LeagueDraftLab"
        env_path = Path(os.environ["LOL_ENV_FILE"]) if os.getenv("LOL_ENV_FILE") else (
            Path.cwd() / ".env" if (Path.cwd() / ".env").exists() else state_dir / ".env"
        )
        values = {**os.environ, **dotenv_values(env_path, encoding="utf-8-sig")}
        def get(key, default=""):
            return values.get(key) or default
        return cls(
            data_dir=Path(get("LOL_DATA_DIR", str(state_dir / "data"))),
            region=get("LOL_REGION", "EUW1").upper(),
            queue=int(get("LOL_QUEUE", "420")),
            target_matches=int(get("LOL_TARGET_MATCHES", "100000")),
            min_matches=max(50000, int(get("LOL_MIN_MATCHES", "50000"))),
            riot_key=get("RIOT_API_KEY"),
            lcu_enabled=get("LOL_LCU_ENABLED", "false").lower() == "true",
            riot_live_approved=get("LOL_RIOT_LIVE_APPROVED", "false").lower() == "true",
            lcu_directory=get("LOL_LCU_DIRECTORY"),
            lcu_ca_file=get("LOL_LCU_CA_FILE"),
        )
