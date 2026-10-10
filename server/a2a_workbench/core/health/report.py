"""Self-contained HTML rendering of a health report."""

from html import escape
from typing import Any

from a2a_workbench.core.health.model import AREAS

_STYLE = """
body{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:32px auto;max-width:980px;color:#1d1d1f;padding:0 16px}
h1{font-size:22px;margin:0}.muted{color:#6b6b70}.score{font-size:40px;font-weight:700}
table{border-collapse:collapse;width:100%;margin:8px 0 18px}td,th{border-bottom:1px solid #e8e7e3;padding:6px 8px;text-align:left;vertical-align:top}
.s{font-weight:600;border-radius:999px;padding:1px 8px;font-size:12px;white-space:nowrap}
.pass{background:#e8f6ee;color:#167a3e}.warn{background:#fdf3e1;color:#a05a00}.fail{background:#fde8e8;color:#b42318}
.not_supported{background:#f2f2ef;color:#6b6b70}.error{background:#eef0ff;color:#3b4bd8}
code{font-family:ui-monospace,Menlo,monospace;font-size:12px}
"""


def render_html(report: dict[str, Any]) -> str:
    """Return the report as one HTML page with inline styles and no scripts."""
    counts = report.get("counts", {})
    rows_by_area: dict[str, list[str]] = {}
    for r in report.get("results", []):
        rows_by_area.setdefault(r["area"], []).append(
            "<tr>"
            f"<td><span class='s {escape(r['status'])}'>{escape(r['status'])}</span></td>"
            f"<td><b>{escape(r['title'])}</b><br><code>{escape(r['check_id'])}</code>"
            f"<div class='muted'>{escape(r['spec_ref'])} · {escape(r['level'].upper())}</div></td>"
            f"<td>{escape(r.get('interface') or 'card')}</td>"
            f"<td><div><b>Expected</b> {escape(r.get('expected') or '')}</div>"
            f"<div><b>Actual</b> {escape(r.get('actual') or '')}</div>"
            + (
                f"<div class='muted'><b>Fix</b> {escape(r['fix_hint'])}</div>"
                if r.get("fix_hint") and r["status"] in ("fail", "warn")
                else ""
            )
            + (
                f"<div class='muted'>Evidence: <code>{escape(', '.join(r['exchange_ids']))}</code></div>"
                if r.get("exchange_ids")
                else ""
            )
            + "</td></tr>"
        )
    sections = "".join(
        f"<h2>{escape(area)} · {escape(AREAS.get(area, ''))}</h2>"
        "<table><tr><th>Status</th><th>Check</th><th>Interface</th><th>Detail</th></tr>"
        + "".join(rows)
        + "</table>"
        for area, rows in sorted(rows_by_area.items())
    )
    summary = " · ".join(f"{escape(k)} {v}" for k, v in counts.items())
    score = report.get("score")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>A2A health report</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>A2A health report · {escape(report['agent']['name'])}</h1>"
        f"<div class='muted'>{escape(report['card_url'])} · {escape(report.get('started_at') or '')}</div>"
        f"<p><span class='score'>{'—' if score is None else score}</span> / 100 <span class='muted'>· {summary}</span></p>"
        f"{sections}</body></html>"
    )
