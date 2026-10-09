"""Security requirements declared by agent cards and skills."""

from a2a.types import AgentCard

Requirement = dict[str, list[str]]


def requirement_alternatives(card: AgentCard, skill_id: str | None = None) -> list[Requirement]:
    """Return the OR-list of requirements (scheme name -> scopes) that apply.

    A skill's own requirements replace the card's when the skill declares any.
    """
    requirements = card.security_requirements
    if skill_id:
        for skill in card.skills:
            if skill.id == skill_id and skill.security_requirements:
                requirements = skill.security_requirements
    return [
        {name: list(scopes.list) for name, scopes in req.schemes.items()} for req in requirements
    ]


def choose_requirement(alternatives: list[Requirement], available: set[str]) -> Requirement | None:
    """Return the first alternative whose schemes all have credentials.

    No alternatives means no authentication is needed (an empty requirement);
    None means none can be satisfied.
    """
    if not alternatives:
        return {}
    for alternative in alternatives:
        if set(alternative) <= available:
            return alternative
    return None
