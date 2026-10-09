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
  kind: "user_message" | "message" | "task" | "status" | "artifact" | "error" | "connection_lost" | "recovered" | "push";
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
  fault?: string | null;
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
  | { kind: "file"; blob_id?: string; url?: string; raw_base64?: string; media_type?: string; filename?: string }
  | { kind: "data"; data: unknown };
export type SendOptions = {
  stream: boolean;
  return_immediately: boolean;
  accepted_output_modes: string[];
  history_length: number | null;
  extensions: string[];
  message_metadata: Record<string, unknown> | null;
  reference_task_ids: string[];
  faults: FaultProfile | null;
  skill_id?: string;
  push?: boolean;
};
export type FaultRule = { kind: string; mode?: string; probability?: number; params?: Record<string, unknown>; match?: Record<string, unknown> };
export type FaultProfile = { name?: string; description?: string; rules: FaultRule[]; seed?: number };
export const DEFAULT_OPTIONS: SendOptions = {
  stream: true,
  return_immediately: false,
  accepted_output_modes: [],
  history_length: null,
  extensions: [],
  message_metadata: null,
  reference_task_ids: [],
  faults: null,
};

export type A2ATask = {
  id: string;
  contextId?: string;
  state: string;
  status?: { state?: string; timestamp?: string; message?: A2AMessage };
  history?: A2AMessage[];
  artifacts?: A2AArtifact[];
  metadata?: Record<string, unknown>;
};
export type TaskPage = { tasks: A2ATask[]; next_page_token: string | null; page_size: number; total_size: number };
export type TaskFilter = {
  context_id?: string;
  status?: string;
  status_timestamp_after?: string;
  include_artifacts?: boolean;
  history_length?: number;
  page_size?: number;
  page_token?: string;
};

export type ConnectionLostData = ErrorData & { task_id: string; last_state: string };
export type RecoveryData = {
  method: "subscribe" | "get_task";
  first_event: string | null;
  snapshot_first: boolean;
  state_before: string | null;
  state_after: string | null;
  missed_states: string[];
  missed_artifacts: string[];
  duplicate_events: number;
  terminal: boolean;
};

export type CredentialInfo = { scheme_name: string; kind: string; preview: string; readable: boolean; expires_at: string | null; updated_at: string; renewal_error?: string | null };
export type SchemeOverview = {
  name: string;
  type: "apiKey" | "http" | "oauth2" | "openIdConnect" | "mutualTLS" | "unknown";
  label: string;
  description: string;
  details: Record<string, any>;
  accepts: string[];
  credential: CredentialInfo | null;
  flows?: string[];
  scopes?: Record<string, string>;
};
export type SecurityOverview = {
  status: "not_required" | "signed_in" | "sign_in_needed";
  schemes: SchemeOverview[];
  requirements: string[][];
  required_scopes?: Record<string, string[]>;
  active: string[];
  missing: string[];
  expired?: string[];
};
export type CredentialInput = { kind: string } & Record<string, string>;

export type OAuthSignInInput = {
  flow: "client_credentials" | "password";
  client_id: string;
  client_secret?: string;
  scopes: string[];
  auth_method: "client_secret_post" | "client_secret_basic";
  username?: string;
  password?: string;
};

export type IntegrationSnippet = { target: string; language: string; install: string; code: string; env: Record<string, string> };
export type ReadinessFinding = { level: "spec" | "advice"; code: string; message: string; path: string; spec_ref: string | null };
export type IntegrationGuide = {
  agent_id: string;
  agent: string;
  card_url: string;
  snippets: Record<string, IntegrationSnippet>;
  guidance: string[];
  readiness: ReadinessFinding[];
};
export type ProviderInfo = {
  provider: "anthropic" | "openai" | "gemini";
  configured: boolean;
  source: "stored" | "env" | "none";
  preview?: string | null;
  base_url?: string | null;
  default_model?: string | null;
};
export type ResponseMode = "rewrite" | "pass_through";
export type AssistantLimits = { max_steps: number; call_timeout_s: number; run_timeout_s: number; token_budget: number };
export type AssistantSession = {
  id: string;
  title: string;
  provider: string;
  model: string;
  response_mode: ResponseMode;
  agent_ids: string[];
  limits: AssistantLimits;
  status: "idle" | "running" | "awaiting_user" | "awaiting_sign_in" | "stopped";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pending: Record<string, any> | null;
  created_at: string;
  updated_at: string;
};
export type AssistantStep = {
  session_id: string;
  seq: number;
  kind:
    | "user"
    | "assistant"
    | "tool_call"
    | "rejected_call"
    | "tool_result"
    | "agent_output"
    | "paused"
    | "resumed"
    | "limit"
    | "error"
    | "done";
  ts: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
};
export type NewAssistantSession = {
  provider: string;
  model?: string;
  response_mode: ResponseMode;
  agent_ids: string[];
  title?: string;
};

export type PushConfig = {
  id: string;
  taskId?: string;
  url: string;
  token?: string;
  authentication?: { scheme: string; credentials?: string };
};
export type PushDelivery = {
  id: string;
  hook_id: string;
  agent_id: string;
  received_at: string;
  verdict: "accepted" | "rejected";
  reasons: string[];
  notes: string[];
  duplicate: boolean;
  kind: string | null;
  task_id: string | null;
  state: string | null;
  headers: Record<string, string>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: Record<string, any> | null;
};
export type PublicUrl = { public_base_url: string; source: "setting" | "tunnel" | "local"; tunnel_running: boolean; cloudflared_installed: boolean };
export type NewPushConfig =
  | { webhook: "workbench" }
  | { webhook: "custom"; url: string; token?: string; auth_scheme?: string; auth_credentials?: string };
