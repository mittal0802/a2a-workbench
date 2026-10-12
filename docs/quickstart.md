# Quick start

No agent at hand? Start the built-in reference agent, which implements every capability on all three bindings:

```bash
a2a-workbench fixtures            # agent on http://127.0.0.1:9999
a2a-workbench serve --open        # in another terminal
```

1. Click **+** in the sidebar and enter `http://127.0.0.1:9999`. The card is fetched and its signature verified.
2. In **Chat**, send `stream` to watch a streamed task, or `ask` to get an `input_required` question.
3. Open **Inspect** to see the exact requests and events.
4. Open the **Health** tab and click **Check health** for a conformance report.

The same from a shell:

```bash
a2a-workbench card http://127.0.0.1:9999 --json
a2a-workbench agents add http://127.0.0.1:9999
a2a-workbench send "Zoo agent" "stream" --json
a2a-workbench check "Zoo agent"
```

Want to see failures? `a2a-workbench fixtures --list-breaks` lists variants of the reference agent that break specific rules, for example `a2a-workbench fixtures --breaks get-unknown-returns`.
