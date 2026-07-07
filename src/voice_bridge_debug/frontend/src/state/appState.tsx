import React, { createContext, useContext, useReducer } from "react";
import type { AgentResult, ConnectionStatus, RobotState, TimelineEvent, WsMessage } from "../types";

interface AppState {
  robotState: RobotState | null;
  timeline: TimelineEvent[];
  agentResult: AgentResult | null;
  connectionStatus: ConnectionStatus;
}

const initialState: AppState = {
  robotState: null,
  timeline: [],
  agentResult: null,
  connectionStatus: {
    websocket: "disconnected",
    ros_node: "unknown",
    last_message_at: null,
    reconnect_attempt: 0,
    error: null,
  },
};

type Action =
  | { type: "ws_message"; message: WsMessage }
  | { type: "history"; events: TimelineEvent[] }
  | { type: "state_snapshot"; robotState: RobotState | null; agentResult: AgentResult | null; timeline: TimelineEvent[] }
  | { type: "connection"; status: Partial<ConnectionStatus> };

function reducer(state: AppState, action: Action): AppState {
  if (action.type === "history") {
    return { ...state, timeline: action.events.slice(-200) };
  }
  if (action.type === "state_snapshot") {
    return {
      ...state,
      robotState: action.robotState,
      agentResult: action.agentResult,
      timeline: action.timeline.slice(-200),
    };
  }
  if (action.type === "connection") {
    return { ...state, connectionStatus: { ...state.connectionStatus, ...action.status } };
  }
  const message = action.message;
  if (message.type === "robot_state") {
    return {
      ...state,
      robotState: message.data,
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  if (message.type === "timeline_event") {
    return {
      ...state,
      timeline: [...state.timeline, message.data].slice(-200),
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  if (message.type === "agent_result") {
    return {
      ...state,
      agentResult: message.data,
      connectionStatus: { ...state.connectionStatus, last_message_at: Date.now(), ros_node: "ready" },
    };
  }
  return { ...state, connectionStatus: { ...state.connectionStatus, ...message.data } };
}

const AppStateContext = createContext<{ state: AppState; dispatch: React.Dispatch<Action> } | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  return <AppStateContext.Provider value={{ state, dispatch }}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const context = useContext(AppStateContext);
  if (context === null) {
    throw new Error("useAppState must be used inside AppStateProvider");
  }
  return context;
}
