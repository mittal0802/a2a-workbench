from a2a_workbench.core.conversations.gaps import analyze_recovery
from a2a_workbench.core.conversations.timeline import TimelineEvent


def ev(kind, **data):
    return TimelineEvent(conversation_id="c", kind=kind, task_id="t", data=data)


def art(aid, *texts, last=False, append=False):
    return ev(
        "artifact",
        artifact={"artifactId": aid, "parts": [{"text": t} for t in texts]},
        assembled={"artifactId": aid, "parts": [{"text": t} for t in texts]},
        append=append,
        last_chunk=last,
    )


def test_snapshot_first_no_gaps_no_duplicates():
    before = [ev("task", state="submitted", task={"id": "t"}), ev("status", state="working")]
    after = [
        ev("task", state="working", task={"id": "t", "status": {"state": "TASK_STATE_WORKING"}}),
        ev("status", state="completed"),
    ]
    out = analyze_recovery(before, after, "subscribe")
    assert out["snapshot_first"] is True and out["first_event"] == "task"
    assert out["state_before"] == "working" and out["state_after"] == "completed"
    assert out["duplicate_events"] == 0 and out["terminal"] is True
    assert out["missed_states"] == ["completed"]


def test_not_snapshot_first_is_reported():
    out = analyze_recovery(
        [ev("status", state="working")], [ev("status", state="completed")], "subscribe"
    )
    assert out["snapshot_first"] is False and out["first_event"] == "status"


def test_duplicates_counted():
    chunk = art("a", "x")
    out = analyze_recovery(
        [ev("status", state="working"), chunk],
        [
            ev("task", state="working", task={"id": "t"}),
            art("a", "x"),
            ev("status", state="completed"),
        ],
        "subscribe",
    )
    assert out["duplicate_events"] == 1


def test_missed_artifacts_from_snapshot_and_stream():
    before = [ev("status", state="working"), art("a", "1")]
    snapshot = ev(
        "task",
        state="working",
        task={"id": "t", "artifacts": [{"artifactId": "a"}, {"artifactId": "b"}]},
    )
    out = analyze_recovery(before, [snapshot, art("c", "z", last=True)], "subscribe")
    assert out["missed_artifacts"] == ["b", "c"]


def test_empty_after():
    out = analyze_recovery([ev("status", state="working")], [], "subscribe")
    assert (
        out["first_event"] is None
        and out["snapshot_first"] is False
        and out["state_after"] == "working"
    )
