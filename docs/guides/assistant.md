# Assistant

The Assistant is an orchestrator LLM acting as an A2A client agent. Each agent you enable becomes one tool built only from its card (description, skills, examples, media types); the tool's inputs are exactly the A2A `Message` / `SendMessageConfiguration` fields. Before anything is sent, calls that break the protocol are rejected and shown: a `context_id` the agent never returned (§3.4.1), an unknown or finished `task_id` (follow-ups go in the same context with `reference_task_ids`), mismatched ids (§3.4.3), or parts the agent's input modes do not accept.

Every call is an ordinary conversation you can open in Chat, with full Inspect, faults and resubscribe, so you see exactly what the orchestrator sent. Streams that drop are resubscribed (§3.5.2), artifacts are the result (§3.7, with a warning when an agent returns output only in messages), and `auth_required` pauses the chat for you to sign in (§7.6.2) while the task is watched.

How results reach you is your choice (A2A leaves presentation to the client):

- **Assistant rewrites**: agents answer the Assistant and it answers you; each agent's raw output stays in its step.
- **Agents speak directly**: agents' output and questions come to you verbatim, your reply to a question goes straight to that agent, and the Assistant's context records what you saw.

Keys are managed on the **Settings** page (sidebar ⚙): one card per provider showing whether a key is saved or comes from the environment (never the key itself), with presets for OpenAI-compatible servers. **Inspect** on an Assistant chat shows every raw HTTP call made to the LLM provider (request and response bodies, headers with keys masked); each reply links to the call that produced it. Chats, conversations and agents can be deleted from the UI (`a2a-workbench chats list|calls|delete` on the CLI).

```bash
A2AW_LLM_API_KEY=… a2a-workbench providers set anthropic       # or set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
a2a-workbench providers set openai --base-url http://localhost:11434/v1   # Ollama, vLLM, LM Studio…
a2a-workbench assist "Book the cheapest flight to SFO" --agents "Travel agent" --json      # NDJSON steps
a2a-workbench assist "ask" --agents "Zoo agent" --response-mode pass-through
a2a-workbench assist "B" --session <id>                       # answer the agent's question
a2a-workbench chats calls <id> --json                         # raw LLM requests and responses (keys masked)
```
