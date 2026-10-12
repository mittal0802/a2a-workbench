# Push notifications

Turn on **Notify me by webhook** in a message's options (or `send --push`), or create a config for any task in the **Notifications** tab (`a2a-workbench push create <agent> <task>`). The Workbench creates a webhook at `/hooks/<id>` with its own token and Bearer credential, puts them in the config (A2A §3.2.2 / §3.1.7), and checks every POST the agent makes:

- `Authorization` must match the config's credentials (A2A §4.3.3, §13.2), else 401;
- the token, when sent, must match (A2A defines the `token` field but not its header; the SDK sends `X-A2A-Notification-Token`, a missing token is only noted);
- the body must be an A2A `StreamResponse` for the task the webhook was created for (§4.3.3), else 400;
- repeats are acknowledged and flagged as duplicates; more than 60 a minute get 429.

Accepted notifications appear as cards in the task's conversation and update its progress; every delivery, accepted or rejected, is in the Notifications inbox with its reasons, masked headers and payload. Webhook secrets are stored only as hashes and masked everywhere.

Agents on other machines cannot reach `127.0.0.1`: set `PUBLIC_BASE_URL`, enter a public URL in **Settings**, or start a Cloudflare quick tunnel there (needs `cloudflared`).

```bash
a2a-workbench send "My agent" "long job" --push --no-stream --return-immediately
a2a-workbench push list "My agent" <task-id> --json
a2a-workbench push deliveries "My agent" --json
a2a-workbench push listen "My agent"            # follow deliveries while `serve` runs
```
