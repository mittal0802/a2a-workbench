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


def as_injector(faults: "FaultProfile | FaultInjector | None") -> "FaultInjector | None":
    """Return ``faults`` as an injector: injectors pass through, profiles get a fresh one."""
    if faults is None or isinstance(faults, FaultInjector):
        return faults
    return FaultInjector(faults)


class InjectorRegistry:
    """Keeps one injector per key while the key's profile stays the same.

    A rule's ``once``, ``nth_call`` and seeded ``probability`` state therefore
    spans every call made under the same key (e.g. a conversation); a changed
    profile starts over.
    """

    def __init__(self) -> None:
        self._injectors: dict[str, tuple[str, FaultInjector]] = {}

    def get(self, key: str, profile: FaultProfile | None) -> FaultInjector | None:
        """Return the injector for ``key`` and ``profile`` (None when there is no profile)."""
        if profile is None:
            self._injectors.pop(key, None)
            return None
        fingerprint = profile.model_dump_json()
        current = self._injectors.get(key)
        if current is None or current[0] != fingerprint:
            current = (fingerprint, FaultInjector(profile))
            self._injectors[key] = current
        return current[1]
