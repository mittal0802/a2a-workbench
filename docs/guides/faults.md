# Fault injection

Break the connection on purpose to see how your agent and its clients recover. Faults are injected beneath the SDK, in the HTTP and gRPC transports: they disturb connections and bytes, never what the SDK sends.

| Preset | Effect |
|---|---|
| `stable` | No injected failures. |
| `flaky_stream` | The next streamed reply drops after 3 events. |
| `slow_agent` | Every request waits 1.5 s before reaching the agent. |
| `offline` | Every connection is refused. |
| `rate_limited` | The next request is answered 429 with Retry-After: 2. |
| `server_error` | Every request is answered 503. |

In the web UI, choose a preset or build your own under **Options → Network conditions** in the chat composer. When a stream drops, the chat offers **Resubscribe** (SubscribeToTask) or **Check status** (GetTask) and, once back in sync, shows the states and results you missed. MCP: `resubscribe`, `check_status`, `fault_presets`.

```bash
a2a-workbench faults presets --json
a2a-workbench send "My agent" "long job" --faults flaky_stream --json
a2a-workbench tasks subscribe "My agent" <task-id>
```
