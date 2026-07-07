import { useEffect } from "react";
import { getJson } from "./api/http";
import { connectWebSocket } from "./api/ws";
import { AgentOutput } from "./components/AgentOutput";
import { AsrInput } from "./components/AsrInput";
import { DecisionTimeline } from "./components/DecisionTimeline";
import { RobotStatus } from "./components/RobotStatus";
import { Header } from "./components/layout/Header";
import { Panel } from "./components/layout/Panel";
import { AppStateProvider, useAppState } from "./state/appState";
import type { AgentResult, RobotState, TimelineEvent } from "./types";
import "./style.css";

interface Snapshot {
  robot_state: RobotState | null;
  agent_result: AgentResult | null;
  timeline: TimelineEvent[];
}

function AppBody() {
  const { state, dispatch } = useAppState();
  useEffect(() => {
    const stop = connectWebSocket(
      (message) => dispatch({ type: "ws_message", message }),
      (status) => dispatch({ type: "connection", status }),
    );
    Promise.all([getJson<Snapshot>("/api/state"), getJson<{ events: TimelineEvent[] }>("/api/history?limit=200")]).then(
      ([snapshot, history]) => {
        dispatch({
          type: "state_snapshot",
          robotState: snapshot.robot_state,
          agentResult: snapshot.agent_result,
          timeline: history.events,
        });
      },
    );
    return stop;
  }, [dispatch]);

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <Header status={state.connectionStatus} />
      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[360px_1fr] lg:grid-rows-2">
        <Panel title="ASR 输入">
          <AsrInput />
        </Panel>
        <Panel title="决策时间线">
          <DecisionTimeline events={state.timeline} />
        </Panel>
        <Panel title="Agent 输出">
          <AgentOutput result={state.agentResult} />
        </Panel>
        <Panel title="机器人状态">
          <RobotStatus state={state.robotState} connection={state.connectionStatus} />
        </Panel>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <AppBody />
    </AppStateProvider>
  );
}
