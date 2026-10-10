---
name: a2a-health-check
description: Check an A2A agent against the A2A specification with A2A Workbench and fix what it reports. Use when building or debugging an A2A agent, before releasing one, or when asked whether an agent is spec-compliant.
---

# A2A health check

A2A Workbench probes an agent through the official `a2a-sdk` and judges each
spec rule: MUST rules `fail`, SHOULD rules `warn`, features the agent card does
not declare are `not_supported` (not counted), and `error` means the Workbench
could not run the check (not counted).

## Run it

With the MCP server (`claude mcp add a2a-workbench -- uvx a2a-workbench mcp`):

1. `run_health_check(agent="<url or registered name>")`. Limit with
   `areas=["F","G"]`; use `interfaces="all"` to test every binding on the card.
2. Read `findings`. Each has `check_id`, `title`, `spec_ref`, `level`,
   `expected`, `actual`, `fix_hint` and `exchange_ids`.
3. For a finding you do not understand, `get_exchange(exchange_id)` shows the
   exact request and response (secrets redacted) and its `checks`.
4. `list_findings(agent=...)` re-reads the latest run later.

From a shell:

```bash
uvx a2a-workbench check <url> --format json > report.json   # exit 1 when a MUST fails
uvx a2a-workbench check <url> --area K --interface all       # text, with fixes
```

## Fix loop

1. Fix `fail` findings first, in the agent's code, following `fix_hint` and
   the cited section of the A2A specification.
2. Re-run only the affected areas (`areas=[...]`) until they pass, then run
   everything once more.
3. Treat `warn` as recommendations from SHOULD rules.
4. `not_supported` is not a defect. If the agent does support the feature,
   declare it on the agent card (for example `capabilities.streaming`).
5. If a finding needs sign-in (`skipped ... add credentials`), store
   credentials first (`set_credential` / `sign_in`) and re-run area I.

## Things to know

- Probes create real tasks, cancel only tasks they created, and create and
  delete push configs on those tasks. Do not point a run at production data
  you cannot afford to touch.
- H4 (push delivery authentication) needs the agent to reach the Workbench's
  webhook; set a public URL or start a tunnel when the agent is remote.
- Only behaviour the A2A specification defines is checked. Do not change the
  agent to satisfy anything else.
