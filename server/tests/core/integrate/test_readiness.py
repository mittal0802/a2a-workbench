from a2a.types import AgentSkill

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.integrate.readiness import readiness


async def test_readiness_spec_and_advice_findings(wb, zoo):
    card = card_from_json((await wb.agents.add(zoo.base_url)).card)
    assert [f for f in readiness(card) if f.level == "spec"] == []
    card.skills.append(AgentSkill(id="", name="Nameless", description="", tags=[]))
    card.skills.append(
        AgentSkill(id="quiet", name="Quiet", description="Does a thing.", tags=["x"])
    )
    card.description = "x" * 700
    found = {(f.level, f.code, f.path) for f in readiness(card)}
    bad = len(card.skills) - 2
    assert ("spec", "skill_field_missing", f"skills[{bad}].id") in found
    assert ("spec", "skill_field_missing", f"skills[{bad}].description") in found
    assert ("spec", "skill_field_missing", f"skills[{bad}].tags") in found
    assert ("advice", "skill_without_examples", "skills[quiet].examples") in found
    assert ("advice", "long_description", "description") in found
    spec = next(f for f in readiness(card) if f.level == "spec")
    assert "AgentSkill" in spec.spec_ref


async def test_no_skills_and_no_modes_are_advice(wb, zoo):
    card = card_from_json((await wb.agents.add(zoo.base_url)).card)
    del card.skills[:]
    del card.default_input_modes[:]
    codes = {f.code for f in readiness(card)}
    assert {"no_skills", "no_input_modes"} <= codes
    assert all(f.level == "advice" for f in readiness(card) if f.code in ("no_skills",))


async def test_live_extended_card_not_configured_is_advice(wb):
    from a2a_workbench.fixtures.runner import ZooServer

    async with ZooServer(grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        guide = await wb.integrate.guide(agent.id)
    assert set(guide.snippets) == {"sdk", "adk", "langgraph", "openai", "claude"}
    assert guide.guidance and any("pass-through" in g.lower() for g in guide.guidance)
    assert not any(f.code == "extended_card_not_configured" for f in guide.readiness)


async def test_declared_but_unconfigured_extended_card_is_advice(wb):
    from a2a_workbench.fixtures.runner import ZooServer

    async with ZooServer(grpc=False, extended_configured=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        guide = await wb.integrate.guide(agent.id)
    finding = next(f for f in guide.readiness if f.code == "extended_card_not_configured")
    assert finding.level == "advice" and "3.3.4" in finding.spec_ref
