# Health checks

The **Health** tab of an agent (also `a2a-workbench check <agent>` and the MCP `run_health_check` tool) runs conformance checks through the official SDK and reports, per spec requirement, what was expected, what came back, how to fix it and the exact requests as evidence:

| Area | What is checked |
|---|---|
| A Discovery | card at the well-known path, REQUIRED fields, interfaces, skills, signatures (§8.4.3), caching (§8.6.1), extended card capability (§3.3.4) |
| B Transports | every declared interface answers, bindings agree (§5.1), unsupported `A2A-Version` refused (§3.6.2) |
| C, E Messaging and results | Task or Message replies, blocking states, generated context ids, unknown / mismatched / finished task ids, `historyLength`, artifacts as results (§3.1.1, §3.2, §3.4, §3.7) |
| F Task operations | GetTask, ListTasks (filter, `nextPageToken`, artifacts omitted, order), CancelTask (§3.1.3–§3.1.5) |
| G Streaming | undeclared streaming refused, Task first, stream closes, SubscribeToTask (§3.1.2, §3.1.6) |
| H Push | undeclared push refused, config round trip, idempotent delete, notifications authenticated (§3.1.7–§3.1.10, §4.3.3) |
| I Security | anonymous and wrong credentials rejected, 401 challenge (§7.4, §3.3.2) |
| J Extensions | required extensions enforced (§3.3.4) |
| K Errors | each error uses the binding's code (§5.4) and carries a code and message |
| L Resilience | resubscribe after a dropped stream, tasks outlive streams, several streams get the same updates (§3.5.2) |

MUST rules fail and SHOULD rules warn; a feature the card does not declare is *not supported* and not counted, and checks the Workbench could not run are listed apart. Score = (pass + ½ warn) ÷ (pass + warn + fail). The checks create real tasks; destructive probes (cancel, push config delete) only touch tasks the run created. Inspect also shows, for every recorded request, the rules that can be judged from it alone (stream first event, ListTasks artifacts, error codes).

```bash
a2a-workbench check http://localhost:9999                         # text report; exit 1 when a MUST fails
a2a-workbench check "My agent" --area F,G,K --interface all --format json > health.json
a2a-workbench check "My agent" --fail-on warn --format html --out health.html
a2a-workbench fixtures --breaks get-unknown-returns,list-order    # a reference agent that breaks rules on purpose
```

Every check is proven by a `broken-*` variant of the reference agent (`fixtures --list-breaks`). Rules the official SDK server makes impossible to break, and rules that would need hand-built requests (malformed JSON-RPC, unknown methods), are not probed.

The full list, with each rule's spec section and fix, is in the [check reference](../reference/checks.md). To run the checks in CI, see [CI](ci.md).
