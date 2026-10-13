from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import REGIONS


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    champion_id: int = Field(default=0, ge=0, le=10000)
    state: Literal["unknown", "hover", "locked"] = "unknown"
    role: Literal["", "TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"] = ""

    @model_validator(mode="after")
    def valid_pick(self):
        if not self.champion_id:
            self.state = "unknown"
        elif self.state == "unknown":
            raise ValueError("A known champion must be a hover or a locked pick")
        return self


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allies: list[Pick] = Field(default_factory=lambda: [Pick() for _ in range(5)], min_length=5, max_length=5)
    enemies: list[Pick] = Field(default_factory=lambda: [Pick() for _ in range(5)], min_length=5, max_length=5)
    side: Literal["blue", "red", "unknown"] = "blue"
    region: str = "EUW1"
    queue: Literal[420, 440] = 420
    patch: str = Field(default="", pattern=r"^(\d+\.\d+)?$")

    @model_validator(mode="after")
    def valid_draft(self):
        if self.region not in REGIONS:
            raise ValueError("Unsupported Riot platform")
        ids = [p.champion_id for p in self.allies + self.enemies if p.champion_id and p.state == "locked"]
        if len(ids) != len(set(ids)):
            raise ValueError("A champion cannot be locked twice in ranked draft")
        for team in (self.allies, self.enemies):
            roles = [p.role for p in team if p.role]
            if len(roles) != len(set(roles)):
                raise ValueError("A known role cannot be assigned twice on one team")
        return self

    def teams(self, include_hovers=True):
        def visible(team):
            return [(p.champion_id, p.role) for p in team if p.champion_id and (include_hovers or p.state == "locked")]
        ally, enemy = visible(self.allies), visible(self.enemies)
        return (ally, enemy) if self.side != "red" else (enemy, ally)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str = "EUW1"
    queue: Literal[420, 440] = 420
    patches: list[str] = Field(default_factory=list, max_length=6)
    tiers: list[str] = Field(default_factory=lambda: ["SILVER", "GOLD", "PLATINUM", "EMERALD"])
    target_matches: int = Field(default=100000, ge=50000, le=1000000)

    @model_validator(mode="after")
    def valid_settings(self):
        from .config import TIERS
        import re
        if self.region not in REGIONS or any(t not in TIERS for t in self.tiers):
            raise ValueError("Unsupported platform or tier")
        if any(not re.fullmatch(r"\d+\.\d+", p) for p in self.patches):
            raise ValueError("Patches must have the form 16.20")
        return self
