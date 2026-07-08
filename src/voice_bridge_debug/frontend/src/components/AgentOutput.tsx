import type { AgentResult } from "../types";

export function AgentOutput({ result }: { result: AgentResult | null }) {
  if (!result) return <p className="text-sm text-slate-500">No agent result yet.</p>;
  const status = result.status ?? "complete";
  const commands = result.commands ?? [];
  const hasCommands = commands.length > 0;
  const hasReply = Boolean(result.reply_text);
  const hasLed = Boolean(result.led);
  if (status === "pending") {
    return (
      <div className="space-y-3 text-sm">
        <div className="font-medium text-amber-700">等待 Agent 输出...</div>
        <div>session: {result.session_id ?? "null"}</div>
        {result.request_text ? <div>input: {result.request_text}</div> : null}
        {result.backend ? <div>backend: {result.backend}</div> : null}
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="space-y-3 text-sm">
        <div className="font-medium text-red-700">Agent error</div>
        <div>session: {result.session_id ?? "null"}</div>
        {result.error ? <div>error: {result.error}</div> : null}
        {result.reply_text ? <div>fallback: {result.reply_text}</div> : null}
      </div>
    );
  }
  return (
    <div className="space-y-3 text-sm">
      <div>session: {result.session_id ?? "null"}</div>
      {hasReply ? <div>reply: {result.reply_text}</div> : null}
      <div>requires_confirmation: {String(result.requires_confirmation)}</div>
      {hasCommands ? (
        <pre className="max-h-64 overflow-auto bg-slate-50 p-2">{JSON.stringify(commands, null, 2)}</pre>
      ) : null}
      {hasLed ? <pre className="max-h-32 overflow-auto bg-slate-50 p-2">{JSON.stringify(result.led, null, 2)}</pre> : null}
      {!hasReply && !hasCommands && !hasLed ? (
        <p className="text-slate-500">Agent 已完成，但没有返回文本、命令或 LED。</p>
      ) : null}
    </div>
  );
}
