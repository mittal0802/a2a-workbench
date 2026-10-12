# Tasks

The **Tasks** tab lists an agent's tasks with the `ListTasks` filters (context, status, updated after, artifacts, history length) and pagination, and opens any task to read its history and artifacts, subscribe to its updates or cancel it.

```bash
a2a-workbench tasks list "My agent" --status working --json
a2a-workbench tasks get "My agent" <task-id> --history-length 10
a2a-workbench tasks subscribe "My agent" <task-id> --json      # NDJSON stream
a2a-workbench tasks cancel "My agent" <task-id>
```

MCP: `list_tasks`, `get_task`, `cancel_task`, `subscribe_task`.
