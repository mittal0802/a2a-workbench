import json

from a2a_workbench.core.health.model import Check, passed, violated
from a2a_workbench.core.health.report import render_html
from a2a_workbench.core.health.runner import HealthService


async def _p(ctx):
    return passed("a task", "a task")


async def _f(ctx):
    return violated("TaskNotFoundError (-32001)", "<script>alert(1)</script>")


async def test_report_json_shape_and_html(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    svc = HealthService(
        wb,
        checks=[
            Check(
                id="x.pass",
                area="F",
                title="Passes",
                spec_ref="A2A §3.1.3",
                level="must",
                fix_hint="",
                run=_p,
            ),
            Check(
                id="x.fail",
                area="F",
                title="Fails",
                spec_ref="A2A §3.1.3",
                level="must",
                fix_hint="Return TaskNotFoundError",
                run=_f,
            ),
        ],
    )
    events = [e async for e in svc.run(agent.id)]
    run_id = events[0].run_id
    report = await svc.report_json(run_id)
    assert report["schema"] == 1
    assert set(report) == {
        "schema",
        "run_id",
        "agent",
        "card_url",
        "interfaces",
        "started_at",
        "finished_at",
        "score",
        "counts",
        "results",
    }
    assert set(report["results"][0]) == {
        "check_id",
        "area",
        "title",
        "spec_ref",
        "level",
        "interface",
        "status",
        "expected",
        "actual",
        "fix_hint",
        "exchange_ids",
        "duration_ms",
    }
    json.dumps(report)
    html = render_html(report)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "Return TaskNotFoundError" in html and str(report["score"]) in html
