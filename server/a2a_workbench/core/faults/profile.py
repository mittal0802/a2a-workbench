"""Fault profiles: declarative descriptions of network failures to inject."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

FaultKind = Literal[
    "refuse",
    "dns_fail",
    "tls_fail",
    "connect_timeout",
    "read_timeout",
    "delay",
    "reset",
    "drop_stream",
    "truncate",
    "garble",
    "http_status",
    "expire_token",
]


class FaultMatch(BaseModel):
    """Which calls a rule applies to; unset fields match everything.

    ``operation`` is the recorded operation label (e.g. ``send_message``),
    ``binding`` the protocol binding, ``nth_call`` the 1-based call count of
    that operation.
    """

    operation: str | None = None
    binding: str | None = None
    nth_call: int | None = Field(default=None, ge=1)


def _non_negative_int(params: dict[str, Any], key: str) -> bool:
    value = params.get(key)
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class FaultRule(BaseModel):
    """One failure to inject, its trigger mode and its parameters."""

    match: FaultMatch = Field(default_factory=FaultMatch)
    kind: FaultKind
    mode: Literal["once", "always", "probability"] = "once"
    probability: float = Field(default=1.0, ge=0.0, le=1.0)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self) -> "FaultRule":
        p = self.params
        if self.kind == "delay" and not _non_negative_int(p, "ms"):
            raise ValueError("delay needs params.ms (integer >= 0)")
        if self.kind == "drop_stream" and not (
            _non_negative_int(p, "after_events") or _non_negative_int(p, "after_ms")
        ):
            raise ValueError("drop_stream needs params.after_events or params.after_ms")
        if self.kind == "truncate" and not _non_negative_int(p, "bytes"):
            raise ValueError("truncate needs params.bytes (integer >= 0)")
        if self.kind == "http_status":
            code = p.get("code")
            if not isinstance(code, int) or not 100 <= code <= 599:
                raise ValueError("http_status needs params.code between 100 and 599")
            if "retry_after" in p and not _non_negative_int(p, "retry_after"):
                raise ValueError("http_status params.retry_after must be an integer >= 0")
        if self.kind == "read_timeout" and "after_ms" in p and not _non_negative_int(p, "after_ms"):
            raise ValueError("read_timeout params.after_ms must be an integer >= 0")
        return self


class FaultProfile(BaseModel):
    """A named, seeded list of fault rules evaluated in order."""

    name: str = "custom"
    description: str = ""
    rules: list[FaultRule] = Field(default_factory=list)
    seed: int = 0


def _preset(name: str, description: str, *rules: dict[str, Any]) -> FaultProfile:
    return FaultProfile.model_validate(
        {"name": name, "description": description, "rules": list(rules)}
    )


PRESETS: dict[str, FaultProfile] = {
    p.name: p
    for p in (
        _preset("stable", "No injected failures."),
        _preset(
            "flaky_stream",
            "The next streamed reply drops after 3 events.",
            {
                "kind": "drop_stream",
                "match": {"operation": "send_message"},
                "params": {"after_events": 3},
            },
        ),
        _preset(
            "slow_agent",
            "Every request waits 1.5 s before reaching the agent.",
            {"kind": "delay", "mode": "always", "params": {"ms": 1500}},
        ),
        _preset("offline", "Every connection is refused.", {"kind": "refuse", "mode": "always"}),
        _preset(
            "rate_limited",
            "The next request is answered 429 with Retry-After: 2.",
            {"kind": "http_status", "params": {"code": 429, "retry_after": 2}},
        ),
        _preset(
            "server_error",
            "Every request is answered 503.",
            {"kind": "http_status", "mode": "always", "params": {"code": 503}},
        ),
    )
}


def load_profile(spec: str) -> FaultProfile:
    """Return the preset named ``spec`` or the profile stored in the JSON file ``spec``.

    Raises:
        ValueError: if ``spec`` is neither a preset nor a readable, valid profile file.
    """
    if spec in PRESETS:
        return PRESETS[spec]
    path = Path(spec)
    if not path.is_file():
        raise ValueError(f"'{spec}' is not a preset ({', '.join(PRESETS)}) or a profile file")
    try:
        return FaultProfile.model_validate(json.loads(path.read_text()))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid fault profile {spec}: {exc}") from exc
