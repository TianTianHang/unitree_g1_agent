import type { WsMessage } from "../types";

export function connectWebSocket(
  onMessage: (message: WsMessage) => void,
  onStatus: (status: {
    websocket: "connecting" | "connected" | "reconnecting" | "disconnected";
    reconnect_attempt?: number;
    error?: string | null;
  }) => void,
): () => void {
  let closed = false;
  let attempt = 0;
  let ws: WebSocket | null = null;

  const open = () => {
    if (closed) return;
    onStatus({ websocket: attempt === 0 ? "connecting" : "reconnecting", reconnect_attempt: attempt });
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${protocol}://${window.location.host}/ws`);
    ws.onopen = () => {
      attempt = 0;
      onStatus({ websocket: "connected", reconnect_attempt: 0, error: null });
    };
    ws.onmessage = (event) => onMessage(JSON.parse(event.data) as WsMessage);
    ws.onerror = () => onStatus({ websocket: "reconnecting", error: "WebSocket error" });
    ws.onclose = () => {
      if (closed) return;
      attempt += 1;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(attempt - 1, 5));
      onStatus({ websocket: "reconnecting", reconnect_attempt: attempt });
      window.setTimeout(open, delay);
    };
  };

  open();
  return () => {
    closed = true;
    ws?.close();
    onStatus({ websocket: "disconnected" });
  };
}
