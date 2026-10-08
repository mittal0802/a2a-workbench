from a2a_workbench.core.registry.diff import card_diff


def test_identical_cards_have_no_diff():
    assert card_diff({"name": "x"}, {"name": "x"}) == []


def test_diff_matches_skills_by_id():
    a = {"name": "x", "skills": [{"id": "s1", "name": "A"}]}
    b = {"name": "x", "skills": [{"id": "s1", "name": "A2"}, {"id": "s2", "name": "B"}]}
    assert card_diff(a, b) == [
        {"path": "skills[s1].name", "change": "changed", "public": "A", "extended": "A2"},
        {
            "path": "skills[s2]",
            "change": "added",
            "public": None,
            "extended": {"id": "s2", "name": "B"},
        },
    ]


def test_diff_extensions_by_uri_and_removed_fields():
    a = {"capabilities": {"extensions": [{"uri": "u1"}]}, "description": "d"}
    b = {"capabilities": {"extensions": [{"uri": "u1"}, {"uri": "u2"}]}}
    out = card_diff(a, b)
    assert {
        "path": "capabilities.extensions[u2]",
        "change": "added",
        "public": None,
        "extended": {"uri": "u2"},
    } in out
    assert {"path": "description", "change": "removed", "public": "d", "extended": None} in out


def test_diff_plain_lists_by_index():
    out = card_diff({"defaultInputModes": ["a"]}, {"defaultInputModes": ["a", "b"]})
    assert out == [
        {"path": "defaultInputModes[1]", "change": "added", "public": None, "extended": "b"}
    ]


def test_signatures_are_ignored():
    assert card_diff({"signatures": [{"s": 1}]}, {"signatures": [{"s": 2}]}) == []
