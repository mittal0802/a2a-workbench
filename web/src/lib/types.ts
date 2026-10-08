export type A2APart = {
  text?: string;
  raw?: string;
  url?: string;
  data?: unknown;
  mediaType?: string;
  filename?: string;
  metadata?: Record<string, unknown>;
};
export type A2AMessage = {
  messageId?: string;
  role?: string;
  parts: A2APart[];
  contextId?: string;
  taskId?: string;
  metadata?: Record<string, unknown>;
};
export type A2AArtifact = {
  artifactId: string;
  name?: string;
  description?: string;
  parts: A2APart[];
  metadata?: Record<string, unknown>;
};
export type InterfaceInfo = {
  url: string;
  binding: string;
  protocol_version: string;
  tenant: string;
  supported: boolean;
};
// The agent card is shown as received; its shape is the A2A AgentCard JSON.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentCardJson = Record<string, any>;
export type SignatureStatus = "verified" | "invalid" | "unsigned" | "unverifiable";
export type Agent = {
  id: string;
  name: string;
  base_url: string;
  card_path: string | null;
  card: AgentCardJson;
  extended_card?: AgentCardJson | null;
  signature_status: SignatureStatus;
  signature_detail: string | null;
  selected_interface_url: string | null;
  interfaces: InterfaceInfo[];
  created_at: string;
  updated_at: string;
};
export type CardPreview = {
  card: AgentCardJson;
  signature_status: SignatureStatus;
  signature_detail: string | null;
  interfaces: InterfaceInfo[];
  default_interface_url: string | null;
  exchange_ids: string[];
};
export type Conversation = {
  id: string;
  agent_id: string;
  title: string;
  origin: string;
  context_id: string | null;
  task_id: string | null;
  task_state: string | null;
  last_seq: number;
  created_at: string;
  updated_at: string;
};
export type ErrorData = {
  category: "transport" | "protocol" | "auth" | "workbench";
  message: string;
  code?: number;
  reason?: string;
  http_status?: number;
  data?: unknown;
};
export type TimelineEvent = {
  conversation_id: string;
  seq: number;
  kind: "user_message" | "message" | "task" | "status" | "artifact" | "error";
  ts: string;
  task_id: string | null;
  context_id: string | null;
  exchange_id: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
};
export type ExchangeSummary = {
  id: string;
  operation: string;
  http_method: string;
  url: string;
  started_at: string;
  status: number | null;
  duration_ms: number | null;
  error: string | null;
  frame_count: number;
  complete?: boolean;
};
export type ExchangeRecord = ExchangeSummary & {
  request_headers: Record<string, string>;
  request_body: string | null;
  response_headers: Record<string, string>;
  response_body: string | null;
  frames: { t_ms: number; data: string }[];
  truncated: boolean;
};
export type PartInput =
  | { kind: "text"; text: string }
  | { kind: "file"; blob_id?: string; url?: string; media_type?: string; filename?: string }
  | { kind: "data"; data: unknown };
export type SendOptions = {
  stream: boolean;
  return_immediately: boolean;
  accepted_output_modes: string[];
  history_length: number | null;
  extensions: string[];
  message_metadata: Record<string, unknown> | null;
  reference_task_ids: string[];
};
export const DEFAULT_OPTIONS: SendOptions = {
  stream: true,
  return_immediately: false,
  accepted_output_modes: [],
  history_length: null,
  extensions: [],
  message_metadata: null,
  reference_task_ids: [],
};
