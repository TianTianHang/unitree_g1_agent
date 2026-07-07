import { useState } from "react";
import { postJson } from "../api/http";

export function AsrInput() {
  const [text, setText] = useState("小宇");
  const [confidence, setConfidence] = useState(0.9);
  const [isFinal, setIsFinal] = useState(true);
  const [source, setSource] = useState("debug");
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setError(null);
    try {
      await postJson<{ ok: boolean }>("/api/asr/publish", { text, confidence, is_final: isFinal, source });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="space-y-3">
      <textarea
        className="h-28 w-full border border-slate-300 p-2 text-sm"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <label className="block text-sm">
        confidence
        <input
          className="ml-2 w-24 border border-slate-300 px-2 py-1"
          type="number"
          min={0}
          max={1}
          step={0.01}
          value={confidence}
          onChange={(event) => setConfidence(Number(event.target.value))}
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isFinal} onChange={(event) => setIsFinal(event.target.checked)} />
        is_final
      </label>
      <input
        className="w-full border border-slate-300 px-2 py-1 text-sm"
        value={source}
        onChange={(event) => setSource(event.target.value)}
      />
      <button className="w-full bg-slate-900 px-3 py-2 text-sm font-medium text-white" onClick={send}>
        发送 ASR
      </button>
      {error ? <p className="text-sm text-red-700">{error}</p> : null}
    </div>
  );
}
