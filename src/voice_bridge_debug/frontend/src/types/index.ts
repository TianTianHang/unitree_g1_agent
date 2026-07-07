export interface ParsedTopicState<T> {
  raw?: string;
  parse_error?: string;
  data?: T;
}

export interface RobotModeFields {
  mode?: string | null;
  control_owner?: string | null;
  mode_source?: string | null;
  sport_fsm_mode?: number | null;
  sport_fsm_id?: number | null;
  source?: string | null;
}

export type RobotModeState = ParsedTopicState<RobotModeFields>;

export interface SafetyFields {
  enabled?: boolean;
  strict_mode?: boolean;
  robot_state?: Record<string, unknown>;
  last_decision?: Record<string, unknown> | null;
  last_rejection_reason?: string | null;
  allow_count?: number;
  reject_count?: number;
}

export type SafetyState = ParsedTopicState<SafetyFields>;

export interface HealthState {
  summary: "ok" | "warn" | "error" | "stale" | "unknown";
  max_level: number | null;
  status_count: number;
  raw: Record<string, unknown> | null;
}

export interface VoiceSession {
  state: "IDLE" | "ACTIVE" | "AGENT_PENDING";
  session_id: string | null;
  started_sec: number | null;
  last_activity_sec: number | null;
}

export interface RobotState {
  robot_mode: RobotModeState | null;
  safety_state: SafetyState | null;
  health: HealthState | null;
  voice_session: VoiceSession | null;
  last_asr_text: string | null;
  last_decision: Record<string, unknown> | null;
  last_error: string | null;
  agent_backend: string | null;
}

export interface TimelineEvent {
  timestamp: number;
  source: string;
  kind: string;
  data: Record<string, unknown>;
  session_id: string | null;
}

export interface AgentCommand {
  kind: string;
  params: Record<string, unknown>;
}

export interface AgentResult {
  commands: AgentCommand[];
  reply_text: string | null;
  led: Record<string, unknown> | null;
  requires_confirmation: boolean;
  session_id: string | null;
}

export interface ConnectionStatus {
  websocket: "connecting" | "connected" | "reconnecting" | "disconnected";
  ros_node: "unknown" | "ready" | "stale" | "error";
  last_message_at: number | null;
  reconnect_attempt: number;
  error: string | null;
}

export type WsMessage =
  | { type: "robot_state"; data: RobotState }
  | { type: "timeline_event"; data: TimelineEvent }
  | { type: "agent_result"; data: AgentResult }
  | { type: "connection_status"; data: Partial<ConnectionStatus> };
