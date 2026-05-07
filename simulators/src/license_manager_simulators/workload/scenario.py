from __future__ import annotations

import random
from dataclasses import dataclass


DEFAULT_MISSING_FEATURE = "missing_feature"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    total: int
    daemon: str | None = None


@dataclass(frozen=True)
class SyntheticUser:
    user: str
    host: str


@dataclass(frozen=True)
class Action:
    kind: str
    feature: str | None = None


class Scenario:
    def __init__(self, port: int, users: list[SyntheticUser], features: list[FeatureSpec], seed: int) -> None:
        self.port = port
        self.users = users
        self.features = features
        self.seed = seed
        self._random = random.Random(seed)

    @classmethod
    def default(cls, port: int, users: int, seed: int) -> "Scenario":
        return cls(
            port=port,
            users=[SyntheticUser(f"user{idx:02d}", f"host{idx:02d}") for idx in range(1, users + 1)],
            features=[
                FeatureSpec("alpha", 5, "vendorA"),
                FeatureSpec("beta", 3, "vendorA"),
                FeatureSpec("gamma", 2, None),
            ],
            seed=seed,
        )

    def license_text(self) -> str:
        lines = [f"PORT {self.port}", "SERVER_NAME 127.0.0.1", "DAEMON vendorA"]
        for feature in self.features:
            daemon = f" DAEMON {feature.daemon}" if feature.daemon else ""
            lines.append(f"FEATURE {feature.name} {feature.total}{daemon}")
        return "\n".join(lines) + "\n"

    def choose_action(self, held_checkout_ids: list[str]) -> Action:
        roll = self._random.random()
        if held_checkout_ids and roll < 0.25:
            return Action("return")
        if roll < 0.35:
            return Action("checkout", "alpha")
        if roll < 0.45:
            return Action("checkout", DEFAULT_MISSING_FEATURE)
        return Action("checkout", self._random.choice([feature.name for feature in self.features]))

    def sleep_seconds(self) -> float:
        return self._random.uniform(0.2, 1.0)
