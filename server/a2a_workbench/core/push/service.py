"""Push notification config operations (A2A §3.1.7–§3.1.10) through the official SDK."""

from typing import Any

from a2a.types import (
    AuthenticationInfo,
    DeleteTaskPushNotificationConfigRequest,
    GetTaskPushNotificationConfigRequest,
    ListTaskPushNotificationConfigsRequest,
    TaskPushNotificationConfig,
)

from a2a_workbench.core.a2a_json import to_json


class PushService:
    """Create, read, list and delete an agent's push notification configs for a task.

    Calls are made with the agent's credentials and recorded like every other
    call; failures raise ``AgentCallError`` with the classified error.
    """

    def __init__(self, tasks: Any) -> None:
        self._tasks = tasks

    async def create(
        self,
        agent_id: str,
        task_id: str,
        *,
        url: str,
        token: str | None = None,
        auth_scheme: str | None = None,
        auth_credentials: str | None = None,
        config_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a config telling the agent to POST the task's updates to ``url``.

        ``token`` and ``auth_scheme``/``auth_credentials`` become the config's
        ``token`` and ``authentication`` (A2A §4.3.1, §4.3.2); ``config_id`` is the
        config's ``id`` (left empty, the agent assigns one).
        """
        config = TaskPushNotificationConfig(task_id=task_id, url=url)
        if config_id:
            config.id = config_id
        if token:
            config.token = token
        if auth_scheme:
            config.authentication.CopyFrom(
                AuthenticationInfo(scheme=auth_scheme, credentials=auth_credentials or "")
            )
        async with self._tasks.client_for(agent_id, "create_push_config") as (client, ctx):
            return to_json(await client.create_task_push_notification_config(config, context=ctx))

    async def get(self, agent_id: str, task_id: str, config_id: str) -> dict[str, Any]:
        """Return one config of the task."""
        req = GetTaskPushNotificationConfigRequest(task_id=task_id, id=config_id)
        async with self._tasks.client_for(agent_id, "get_push_config") as (client, ctx):
            return to_json(await client.get_task_push_notification_config(req, context=ctx))

    async def list(
        self,
        agent_id: str,
        task_id: str,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Return ``{"configs", "next_page_token"}`` for the task."""
        req = ListTaskPushNotificationConfigsRequest(task_id=task_id)
        if page_size:
            req.page_size = page_size
        if page_token:
            req.page_token = page_token
        async with self._tasks.client_for(agent_id, "list_push_configs") as (client, ctx):
            resp = await client.list_task_push_notification_configs(req, context=ctx)
        return {
            "configs": [to_json(c) for c in resp.configs],
            "next_page_token": resp.next_page_token or None,
        }

    async def delete(self, agent_id: str, task_id: str, config_id: str) -> None:
        """Delete one config of the task (idempotent at the agent, A2A §3.1.10)."""
        req = DeleteTaskPushNotificationConfigRequest(task_id=task_id, id=config_id)
        async with self._tasks.client_for(agent_id, "delete_push_config") as (client, ctx):
            await client.delete_task_push_notification_config(req, context=ctx)
