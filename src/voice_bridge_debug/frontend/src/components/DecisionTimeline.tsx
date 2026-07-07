import type { TimelineEvent } from "../types";

export function DecisionTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="h-full space-y-2 overflow-auto text-sm">
      {events.length === 0 ? <p className="text-slate-500">No events yet.</p> : null}
      {events.map((event, index) => (
        <details key={`${event.timestamp}-${index}`} className="border-l-2 border-slate-300 pl-3">
          <summary>
            {new Date(event.timestamp * 1000).toLocaleTimeString()} {event.source}: {event.kind}
          </summary>
          {event.source === "voice_debug" &&
          event.kind === "agent_result" &&
          !events.some((item) => item.kind === "agent_tool_event") ? (
            <p className="my-2 text-slate-500">未提供工具事件</p>
          ) : null}
          <pre className="mt-2 overflow-auto bg-slate-50 p-2">{JSON.stringify(event.data, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}
