"""Deciding, call by call, which fault rule applies."""

import random
from collections import Counter

from a2a_workbench.core.faults.profile import FaultProfile, FaultRule


class FaultInjector:
    """Evaluates a profile's rules against successive calls.

    Each call increments a per-operation counter; the first matching rule
    wins. ``once`` rules fire a single time, ``always`` rules on every match,
    and ``probability`` rules draw from a generator seeded with the profile's
    seed, so a run is reproducible.
    """

    def __init__(self, profile: FaultProfile) -> None:
        self.profile = profile
        self._counts: Counter[str] = Counter()
        self._fired: set[int] = set()
        self._rng = random.Random(profile.seed)

    def decide(self, operation: str, binding: str) -> FaultRule | None:
        """Register one call of ``operation`` over ``binding`` and return the rule to apply."""
        self._counts[operation] += 1
        count = self._counts[operation]
        for index, rule in enumerate(self.profile.rules):
            m = rule.match
            if m.operation is not None and m.operation != operation:
                continue
            if m.binding is not None and m.binding != binding:
                continue
            if m.nth_call is not None and m.nth_call != count:
                continue
            if rule.mode == "once":
                if index in self._fired:
                    continue
                self._fired.add(index)
                return rule
            if rule.mode == "probability" and self._rng.random() >= rule.probability:
                continue
            return rule
        return None
