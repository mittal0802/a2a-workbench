# Connect, chat and inspect

**Connect** an agent from the sidebar's **+** (CLI `a2a-workbench agents add <url>`, MCP `add_agent`). The Workbench fetches the Agent Card from the well-known path (or the card URL you give), verifies its JWS signatures and lists the interfaces it declares. Pick the interface (JSON-RPC, HTTP+JSON or gRPC) and protocol version (1.0, or 0.3 through the SDK's compat layer). When the card declares an extended card, the **About** tab fetches it and shows what differs from the public card.

**Chat** sends messages with every part type (text, files, URLs, JSON data) and every `SendMessageConfiguration` option, under **Options** in the composer: streaming, return immediately, history length, accepted output modes, extensions, metadata and push notifications. Replies stream live, `input_required` questions get an answer box, and **Stop** cancels the task.

**Inspect** shows every request, response and server-sent event of a conversation exactly as it went over the wire, with secrets redacted, plus the spec rules that can be judged from each exchange alone. Copy or export any exchange as JSON (MCP `list_exchanges`, `get_exchange`).

```bash
a2a-workbench card http://localhost:9999 --json          # fetch + verify the card
a2a-workbench send "My agent" "hello" --json             # NDJSON timeline events
a2a-workbench send http://localhost:9999 "inspect" --file report.pdf --data '{"n": 1}' \
  --accept application/json --history-length 5 --metadata '{"k": "v"}'
```
