"""How ready an Agent Card is for being called by other agents.

``spec`` findings are fields the A2A proto marks REQUIRED; everything else is
``advice``: things the specification does not require but that help an
orchestrator pick the agent and phrase requests well.
"""

from typing import Literal

from a2a.types import AgentCard
from pydantic import BaseModel

LONG_DESCRIPTION = 600


class Finding(BaseModel):
    """One readiness observation, with where it applies and the spec reference if any."""

    level: Literal["spec", "advice"]
    code: str
    message: str
    path: str
    spec_ref: str | None = None


def readiness(card: AgentCard) -> list[Finding]:
    """Return readiness findings for ``card`` (card fields only, no network)."""
    out: list[Finding] = []
    if not card.skills:
        out.append(
            Finding(
                level="advice",
                code="no_skills",
                message="The card lists no skills, so an orchestrator has little to choose by.",
                path="skills",
            )
        )
    for i, skill in enumerate(card.skills):
        for field in ("id", "name", "description", "tags"):
            if not getattr(skill, field):
                out.append(
                    Finding(
                        level="spec",
                        code="skill_field_missing",
                        message=f"Skill {i} has no {field}; the A2A proto marks it REQUIRED.",
                        path=f"skills[{i}].{field}",
                        spec_ref="a2a.proto AgentSkill (field_behavior = REQUIRED)",
                    )
                )
        label = skill.id or str(i)
        if not skill.examples:
            out.append(
                Finding(
                    level="advice",
                    code="skill_without_examples",
                    message=f"Skill '{label}' has no examples; examples help an orchestrator "
                    "phrase requests the way the agent expects.",
                    path=f"skills[{label}].examples",
                )
            )
    if len(card.description) > LONG_DESCRIPTION:
        out.append(
            Finding(
                level="advice",
                code="long_description",
                message=f"The description is {len(card.description)} characters. Keep it to "
                "what the agent does; describe capabilities as skills.",
                path="description",
            )
        )
    has_modes = card.default_input_modes or any(s.input_modes for s in card.skills)
    if not has_modes:
        out.append(
            Finding(
                level="advice",
                code="no_input_modes",
                message="No input media types are declared, so callers cannot tell whether "
                "the agent accepts JSON or files.",
                path="defaultInputModes",
                spec_ref="a2a.proto AgentCard.default_input_modes",
            )
        )
    if not card.default_output_modes and not any(s.output_modes for s in card.skills):
        out.append(
            Finding(
                level="advice",
                code="no_output_modes",
                message="No output media types are declared.",
                path="defaultOutputModes",
                spec_ref="a2a.proto AgentCard.default_output_modes",
            )
        )
    return out
