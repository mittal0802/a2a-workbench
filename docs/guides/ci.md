# Health checks in CI

`a2a-workbench check` exits `1` when any result reaches `--fail-on` (or nothing could be checked), so it can gate a pipeline. Progress goes to stderr; the report goes to stdout or `--out`.

```yaml
# .github/workflows/a2a.yml
name: A2A conformance
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - name: Start the agent under test
        run: ./start-my-agent.sh &          # your agent, listening on :9999
      - name: Check it
        run: |
          uvx a2a-workbench check http://127.0.0.1:9999 \
            --fail-on fail --format json --out a2a-health.json
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: a2a-health
          path: a2a-health.json
```

Useful options:

| Option | Effect |
|---|---|
| `--area F,G,K` | Only these areas (see the [check reference](../reference/checks.md)). |
| `--interface all` | Check every interface the card declares, not just the selected one. |
| `--fail-on warn` | Also fail on SHOULD rules. |
| `--format html --out report.html` | A self-contained HTML report. |
| `--faults flaky_stream` | Run the probes under a fault preset. |

Agents that require sign-in: store the credential first, from environment variables so it never appears in the job log, for example `A2AW_TOKEN=${{ secrets.AGENT_TOKEN }} a2a-workbench auth set <agent> <scheme>` after `a2a-workbench agents add <url>`.
