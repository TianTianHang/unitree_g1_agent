import type { ConnectionStatus, RobotState } from "../types";

export function RobotStatus({ state, connection }: { state: RobotState | null; connection: ConnectionStatus }) {
  return (
    <div className="space-y-3 text-sm">
      <div>WebSocket: {connection.websocket}</div>
      <div>ROS2: {connection.ros_node}</div>
      <div>Health: {state?.health?.summary ?? "unknown"}</div>
      <div>Session: {state?.voice_session?.state ?? "unknown"}</div>
      <div>Agent Backend: {state?.agent_backend ?? "unknown"}</div>
      <pre className="max-h-64 overflow-auto bg-slate-50 p-2">
        {JSON.stringify({ mode: state?.robot_mode, safety: state?.safety_state, last_error: state?.last_error }, null, 2)}
      </pre>
    </div>
  );
}
