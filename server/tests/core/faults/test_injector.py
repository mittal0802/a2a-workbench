from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultMatch, FaultProfile, FaultRule


def _inj(*rules, seed=0):
    return FaultInjector(FaultProfile(rules=list(rules), seed=seed))


def test_once_fires_only_first_match():
    inj = _inj(FaultRule(kind="refuse"))
    assert inj.decide("send_message", "JSONRPC").kind == "refuse"
    assert inj.decide("send_message", "JSONRPC") is None


def test_always_fires_every_time():
    inj = _inj(FaultRule(kind="delay", mode="always", params={"ms": 1}))
    assert all(inj.decide("x", "JSONRPC") for _ in range(3))


def test_match_operation_binding_and_nth_call():
    rule = FaultRule(
        kind="reset",
        mode="always",
        match=FaultMatch(operation="send_message", binding="GRPC", nth_call=2),
    )
    inj = _inj(rule)
    assert inj.decide("send_message", "GRPC") is None
    assert inj.decide("get_task", "GRPC") is None
    assert inj.decide("send_message", "GRPC").kind == "reset"
    assert inj.decide("send_message", "GRPC") is None


def test_binding_mismatch_never_fires():
    inj = _inj(FaultRule(kind="refuse", mode="always", match=FaultMatch(binding="GRPC")))
    assert inj.decide("send_message", "JSONRPC") is None


def test_probability_mode_is_seeded():
    rule = FaultRule(kind="refuse", mode="probability", probability=0.5)

    def sequence(seed):
        inj = _inj(rule, seed=seed)
        return [inj.decide("x", "JSONRPC") is not None for _ in range(40)]

    assert sequence(7) == sequence(7)
    assert any(sequence(7)) and not all(sequence(7))
    assert sequence(7) != sequence(8)


def test_empty_profile_never_fires():
    assert _inj().decide("send_message", "JSONRPC") is None
