import type { DiffEntry } from "../features/about/CardDiff";
import type {
  Agent,
  AgentCardJson,
  CardPreview,
  Conversation,
  ExchangeRecord,
  ExchangeSummary,
  PartInput,
  A2ATask,
  CredentialInfo,
  CredentialInput,
  SecurityOverview,
  FaultProfile,
  SendOptions,
  TaskFilter,
  TaskPage,
  TimelineEvent,
} from "./types";

function query(params: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** An API failure with the server's error category. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public category: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = init.body instanceof FormData ? {} : { "content-type": "application/json" };
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = body.error ?? { category: "workbench", message: body.detail ?? res.statusText };
    const message = typeof err.message === "string" ? err.message : JSON.stringify(body.detail ?? err);
    throw new ApiError(res.status, err.category ?? "workbench", message);
  }
  return body as T;
}

const json = (b: unknown) => JSON.stringify(b);

export const api = {
  listAgents: () => call<Agent[]>("/api/agents"),
  getAgent: (id: string) => call<Agent>(`/api/agents/${id}`),
  previewCard: (url: string) => call<CardPreview>("/api/cards/preview", { method: "POST", body: json({ url }) }),
  addAgent: (url: string) => call<Agent>("/api/agents", { method: "POST", body: json({ url }) }),
  deleteAgent: (id: string) => call<void>(`/api/agents/${id}`, { method: "DELETE" }),
  patchAgent: (id: string, selected_interface_url: string) =>
    call<Agent>(`/api/agents/${id}`, { method: "PATCH", body: json({ selected_interface_url }) }),
  refreshAgent: (id: string) => call<Agent>(`/api/agents/${id}/refresh`, { method: "POST" }),
  extendedCard: (id: string) =>
    call<{ card: AgentCardJson; diff: DiffEntry[]; exchange_ids: string[] }>(`/api/agents/${id}/extended-card`, {
      method: "POST",
    }),
  listConversations: (agentId: string) => call<Conversation[]>(`/api/agents/${agentId}/conversations`),
  createConversation: (agent_id: string) =>
    call<Conversation>("/api/conversations", { method: "POST", body: json({ agent_id }) }),
  getConversation: (id: string) =>
    call<{ conversation: Conversation; events: TimelineEvent[] }>(`/api/conversations/${id}`),
  sendMessage: (id: string, parts: PartInput[], options: SendOptions) =>
    call<{ accepted: boolean }>(`/api/conversations/${id}/messages`, {
      method: "POST",
      body: json({ parts, options }),
    }),
  cancel: (id: string) => call<{ accepted: boolean }>(`/api/conversations/${id}/cancel`, { method: "POST" }),
  resubscribe: (id: string, force = false) =>
    call<{ accepted: boolean }>(`/api/conversations/${id}/resubscribe`, { method: "POST", body: json({ force }) }),
  checkStatus: (id: string) => call<{ accepted: boolean }>(`/api/conversations/${id}/check-status`, { method: "POST" }),
  uploadBlob: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<{ id: string; media_type: string; filename: string | null; size: number }>("/api/blobs", {
      method: "POST",
      body: form,
    });
  },
  listExchanges: (conversationId: string) =>
    call<ExchangeSummary[]>(`/api/exchanges?conversation_id=${encodeURIComponent(conversationId)}`),
  getExchange: (id: string) => call<ExchangeRecord>(`/api/exchanges/${id}`),
  security: (agentId: string) => call<SecurityOverview>(`/api/agents/${agentId}/security`),
  putCredential: (agentId: string, scheme: string, body: CredentialInput) =>
    call<CredentialInfo>(`/api/agents/${agentId}/credentials/${encodeURIComponent(scheme)}`, {
      method: "PUT",
      body: json(body),
    }),
  deleteCredential: (agentId: string, scheme: string) =>
    call<void>(`/api/agents/${agentId}/credentials/${encodeURIComponent(scheme)}`, { method: "DELETE" }),
  faultPresets: () => call<FaultProfile[]>("/api/fault-presets"),
  listTasks: (agentId: string, filter: TaskFilter) => call<TaskPage>(`/api/agents/${agentId}/tasks${query(filter)}`),
  getTask: (agentId: string, taskId: string, history_length?: number) =>
    call<A2ATask>(`/api/agents/${agentId}/tasks/${encodeURIComponent(taskId)}${query({ history_length })}`),
  watchTask: (agentId: string, taskId: string) =>
    call<{ conversation_id: string }>(`/api/agents/${agentId}/tasks/${encodeURIComponent(taskId)}/watch`, {
      method: "POST",
    }),
  cancelTask: (agentId: string, taskId: string) =>
    call<A2ATask>(`/api/agents/${agentId}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST", body: "{}" }),
};
