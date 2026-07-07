import type { ConnectionStatus } from "../../types";

export function Header({ status }: { status: ConnectionStatus }) {
  const connected = status.websocket === "connected";
  return (
    <header className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-5 py-3">
      <h1 className="text-base font-semibold text-slate-900">G1 Voice Bridge Debug Panel</h1>
      <div className="flex items-center gap-3 text-sm text-slate-600">
        <span className={connected ? "text-emerald-700" : "text-red-700"}>{status.websocket}</span>
        <span>ROS2: {status.ros_node}</span>
      </div>
    </header>
  );
}
