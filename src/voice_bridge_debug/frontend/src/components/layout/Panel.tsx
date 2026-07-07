export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-h-0 border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
      {children}
    </section>
  );
}
