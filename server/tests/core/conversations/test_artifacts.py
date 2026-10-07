from a2a.types import Artifact, Part, TaskArtifactUpdateEvent

from a2a_workbench.core.conversations.artifacts import ArtifactAssembler


def _ev(text, append, last, aid="a", name="n"):
    return TaskArtifactUpdateEvent(
        task_id="t",
        artifact=Artifact(artifact_id=aid, name=name, parts=[Part(text=text)]),
        append=append,
        last_chunk=last,
    )


def test_append_concatenates_parts_in_order():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False))
    asm.apply(_ev("b", True, False, name=""))
    out = asm.apply(_ev("c", True, True, name=""))
    assert [p.text for p in out.parts] == ["a", "b", "c"]
    assert out.name == "n"


def test_non_append_replaces():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False))
    assert [p.text for p in asm.apply(_ev("z", False, True)).parts] == ["z"]


def test_append_without_prior_starts_new():
    assert [p.text for p in ArtifactAssembler().apply(_ev("x", True, True)).parts] == ["x"]


def test_artifacts_are_isolated_per_id():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False, "1"))
    assert [p.text for p in asm.apply(_ev("b", True, False, "2")).parts] == ["b"]


def test_seed_then_append():
    asm = ArtifactAssembler()
    asm.seed("t", Artifact(artifact_id="a", parts=[Part(text="s")]))
    assert [p.text for p in asm.apply(_ev("x", True, True)).parts] == ["s", "x"]


def test_returned_artifact_is_not_mutated_by_later_chunks():
    asm = ArtifactAssembler()
    first = asm.apply(_ev("a", False, False))
    asm.apply(_ev("b", True, True))
    assert [p.text for p in first.parts] == ["a"]
