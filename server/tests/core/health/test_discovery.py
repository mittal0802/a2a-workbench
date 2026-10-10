import pytest


async def test_compliant_zoo_passes_discovery(health_of):
    results, _ = await health_of(["A"])
    assert {k: v.status for k, v in results.items()} == {
        "A1.card_reachable": "pass",
        "A2.card_required_fields": "pass",
        "A3.card_interfaces": "pass",
        "A4.card_skills": "pass",
        "A5.card_signature": "pass",
        "A6.card_caching": "pass",
        "A7.extended_capability": "pass",
    }


async def test_unsigned_card_is_not_supported(health_of):
    results, _ = await health_of(["A"], signed=False)
    assert results["A5.card_signature"].status == "not_supported"


@pytest.mark.parametrize(
    "brk,check,status",
    [
        ("card-missing-fields", "A2.card_required_fields", "fail"),
        ("card-no-version", "A3.card_interfaces", "fail"),
        ("skill-no-tags", "A4.card_skills", "fail"),
        ("bad-signature", "A5.card_signature", "fail"),
        ("card-no-cache", "A6.card_caching", "warn"),
        ("extended-ignores-capability", "A7.extended_capability", "fail"),
    ],
)
async def test_detects_discovery_violations(health_of, brk, check, status):
    results, _ = await health_of(["A"], breaks=[brk])
    assert results[check].status == status, results[check]
    assert results[check].fix_hint and results[check].spec_ref
    others = {
        k: v.status for k, v in results.items() if k != check and v.status in ("fail", "warn")
    }
    assert others == {} or brk == "card-no-version", others
