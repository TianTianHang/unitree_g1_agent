import type { AgentResult } from "../types";

export function AgentOutput({ result }: { result: AgentResult | null }) {
  if (!result) return <p className="text-sm text-slate-500">No agent result yet.</p>;
  return (
    <div className="space-y-3 text-sm">
      <div>reply: {result.reply_text ?? "null"}</div>
      <div>requires_confirmation: {String(result.requires_confirmation)}</div>
      <pre className="max-h-64 overflow-auto bg-slate-50 p-2">{JSON.stringify(result.commands, null, 2)}</pre>
    </div>
  );
}
