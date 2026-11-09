import { chimeMuted, playChime, setChimeMuted, unlockChime } from "../lib/chime";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";

const usd = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(2)}`);

function CostPanel({ cost, title }: { cost: any; title: string }) {
  if (!cost) return null;
  const steps = Object.entries<any>(cost.ai?.by_step ?? {});
  const apis = Object.entries<any>(cost.google?.by_api ?? {}).filter(([, v]) => v.calls > 0);
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <span className="text-lg font-semibold text-slate-900">{usd(cost.total_usd)}</span>
      </div>
      <div className="grid grid-cols-2 gap-4 mt-3 text-sm">
        <div>
          <div className="flex justify-between font-medium text-slate-700">
            <span>AI</span><span>{usd(cost.ai?.total_usd)}</span>
          </div>
          {steps.length === 0 && <p className="text-slate-400 text-xs mt-1">none</p>}
          {steps.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs text-slate-500 mt-1" title={v.model}>
              <span>{k}</span><span>{usd(v.usd)}</span>
            </div>
          ))}
        </div>
        <div>
          <div className="flex justify-between font-medium text-slate-700">
            <span>Google</span><span>{usd(cost.google?.total_usd)}</span>
          </div>
          {apis.length === 0 && <p className="text-slate-400 text-xs mt-1">none</p>}
          {apis.map(([k, v]) => (
            <div key={k} className="flex justify-between text-xs text-slate-500 mt-1">
              <span>{k} × {v.calls}</span><span>{usd(v.usd)}</span>
            </div>
          ))}
        </div>
      </div>
      {(cost.warnings ?? []).map((w: string) => (
        <p key={w} className="text-xs text-amber-700 mt-2">⚠ {w}</p>
      ))}
    </div>
  );
}

const fkey = (f: File) => `${f.name}|${f.size}|${f.lastModified}`;
const fsize = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "📕";
  if (["doc", "docx"].includes(ext)) return "📘";
  if (["xls", "xlsx", "csv"].includes(ext)) return "📗";
  if (["png", "jpg", "jpeg", "heic", "webp", "gif"].includes(ext)) return "🖼";
  if (ext === "zip") return "🗜";
  return "📄";
}

function FileList({ files, onRemove }: { files: File[]; onRemove: (f: File) => void }) {
  return (
    <ul className="divide-y divide-slate-100 border border-slate-200 rounded-md">
      {files.map((f) => (
        <li key={fkey(f)} className="flex items-center gap-2 px-2 py-1 text-sm">
          <span>{fileIcon(f.name)}</span>
          <span className="flex-1 truncate text-slate-700">{f.name}</span>
          <span className="text-xs text-slate-400">{fsize(f.size)}</span>
          <button type="button" aria-label={`Remove ${f.name}`} onClick={() => onRemove(f)}
            className="px-1 text-slate-400 hover:text-red-600">✕ Remove</button>
        </li>
      ))}
    </ul>
  );
}

function AnswerBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const max = 12 * 22;
    el.style.height = `${Math.min(el.scrollHeight + 2, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [value]);
  return (
    <textarea ref={ref} rows={2} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
      className="mt-1 w-full border border-slate-300 rounded px-2 py-1 text-sm resize-y whitespace-pre-wrap break-words" />
  );
}

function AttachmentPicker({ files, setFiles, disabled }: { files: File[]; setFiles: (f: File[]) => void; disabled: boolean }) {
  const [over, setOver] = useState(false);
  const filesRef = useRef<File[]>(files);
  filesRef.current = files;
  const add = (list: FileList | File[] | null) => {
    if (!list) return;
    const have = new Set(filesRef.current.map(fkey));
    const fresh: File[] = [];
    for (const f of Array.from(list)) { if (!have.has(fkey(f))) { have.add(fkey(f)); fresh.push(f); } }
    if (fresh.length) setFiles([...filesRef.current, ...fresh]);
  };
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  useEffect(() => { folderInput.current?.setAttribute("webkitdirectory", ""); }, []);
  const picked = (e: React.ChangeEvent<HTMLInputElement>) => { add(e.target.files); e.target.value = ""; };
  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) add(e.dataTransfer.files); }}
        className={`border-2 border-dashed rounded-lg p-4 text-center text-sm ${over ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-slate-50"}`}
      >
        <p className="text-slate-600">Drag files here, or</p>
        <div className="flex justify-center gap-2 mt-2">
          <button type="button" disabled={disabled} onClick={() => fileInput.current?.click()}
            className="px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm font-medium disabled:opacity-40">Add files</button>
          <button type="button" disabled={disabled} onClick={() => folderInput.current?.click()}
            className="px-3 py-1.5 rounded-md border border-blue-600 text-blue-700 text-sm font-medium disabled:opacity-40">Add folder</button>
        </div>
        <p className="text-xs text-slate-400 mt-2">You can add more from other folders; everything is kept in the list below.</p>
        <input ref={fileInput} type="file" multiple className="hidden" onChange={picked} />
        <input ref={folderInput} type="file" multiple className="hidden" onChange={picked} />
      </div>
      {files.length > 0 && (
        <>
          <div className="flex justify-between text-xs text-slate-500">
            <span>{files.length} file{files.length === 1 ? "" : "s"} attached</span>
            <button type="button" disabled={disabled} onClick={() => setFiles([])} className="text-blue-600 hover:underline">Clear all</button>
          </div>
          <FileList files={files} onRemove={(f) => setFiles(files.filter((x) => fkey(x) !== fkey(f)))} />
        </>
      )}
    </div>
  );
}

export function AigV2Tab() {
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState("");
  const [intake, setIntake] = useState<File | null>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [showCancelled, setShowCancelled] = useState(false);
  const [days, setDays] = useState("");
  const [sections, setSections] = useState<string[]>([]);
  const timer = useRef<number | null>(null);
  const [muted, setMuted] = useState<boolean>(chimeMuted());

  const loadRuns = useCallback(() => api.v2Runs().then((r) => setRuns(r.runs)).catch(() => {}), []);
  const loadRun = useCallback((id: string) => api.v2Run(id).then((r) => {
    setRun(r);
    setAnswers((a) => ({ ...Object.fromEntries(r.questions.map((q: any) => [q.id, ""])), ...(r.answers ?? {}), ...a }));
  }).catch((e) => setError(e.message)), []);

  useEffect(() => { loadRuns(); }, [loadRuns]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  useEffect(() => { if (runId) { setRun(null); setAnswers({}); loadRun(runId); } else setRun(null); }, [runId, loadRun]);

  const poll = useCallback((id: string) => {
    api.v2Job(id).then((j) => {
      setJob(j);
      if (j.status === "queued" || j.status === "running") {
        timer.current = window.setTimeout(() => poll(id), 1500);
        return;
      }
      loadRuns();
      if (j.status !== "cancelled") playChime(j.status === "error" ? "error" : "done");
      const target = j.result?.run_id ?? j.run_id;
      if (target) { if (target === runId) loadRun(target); else setRunId(target); }
    }).catch((e) => { setError(e.message); setJob(null); });
  }, [loadRuns, loadRun, runId]);

  async function launch(fn: () => Promise<any>) {
    unlockChime();
    setError(""); setJob(null);
    try {
      const j = await fn();
      setJob(j);
      poll(j.id);
    } catch (e: any) { setError(e.message); }
  }

  const busy = job && (job.status === "queued" || job.status === "running");
  const unanswered = run ? run.questions.filter((q: any) => !(answers[q.id] ?? "").trim()) : [];
  const built = run?.stage === "built";
  const cancelled = run?.stage === "cancelled";
  const jobBusy = !!busy;
  async function doCancel() {
    setConfirmCancel(false);
    try {
      if (runId) await api.v2Cancel(runId);
      else if (job?.id) await api.v2CancelJob(job.id);
      loadRuns(); if (runId) loadRun(runId);
    } catch (e: any) { setError(e.message); }
  }
  const visibleRuns = runs.filter((r) => showCancelled || r.stage !== "cancelled");

  return (
    <div className="flex gap-6 max-w-6xl mx-auto">
      <aside className="w-64 flex-shrink-0 space-y-2">
        <button
          onClick={() => { setRunId(null); setJob(null); setError(""); }}
          className="w-full px-3 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
        >+ New run</button>
        <label className="flex items-center gap-1 text-xs text-slate-500 px-1">
          <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />Show cancelled
        </label>
        <div className="flex items-center justify-between text-xs text-slate-500 px-1">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={!muted}
              onChange={(e) => { const m = !e.target.checked; setMuted(m); setChimeMuted(m); if (!m) { unlockChime(); playChime("done"); } }}
            />Chime when a stage finishes
          </label>
          <button type="button" className="underline hover:text-slate-700" onClick={() => { unlockChime(); playChime("done"); }}>Test</button>
        </div>
        {visibleRuns.map((r) => (
          <button
            key={r.run_id}
            onClick={() => { setRunId(r.run_id); setJob(null); setError(""); }}
            className={`w-full text-left px-3 py-2 rounded-md border text-xs ${r.run_id === runId ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
          >
            <div className="font-medium text-slate-700 truncate">{r.title || "(no names)"}</div>
            <div className="text-slate-400 font-mono truncate">{r.run_id}</div>
            <div className="flex justify-between text-slate-500 mt-1">
              <span className={r.stage === "cancelled" ? "px-1 rounded bg-slate-200 text-slate-600" : ""}>{r.stage === "cancelled" ? "Cancelled" : r.stage}</span>
              <span>{r.total_usd == null ? "" : `AI ${usd(r.ai_usd)} · G ${usd(r.google_usd)}`}</span>
            </div>
          </button>
        ))}
      </aside>

      <section className="flex-1 space-y-4 min-w-0">
        {error && <p className="text-red-600 text-sm whitespace-pre-wrap">{error}</p>}

        {confirmCancel && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-5 max-w-sm space-y-3 shadow-lg">
              <p className="text-sm text-slate-800 font-medium">Cancel this run?</p>
              <p className="text-sm text-slate-600">Work done so far is kept and costs already spent stay recorded, but the run will not continue.</p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setConfirmCancel(false)} className="px-3 py-1.5 rounded-md border border-slate-300 text-sm">Keep run</button>
                <button onClick={doCancel} className="px-3 py-1.5 rounded-md bg-red-600 text-white text-sm font-medium">Yes, cancel run</button>
              </div>
            </div>
          </div>
        )}

        {(runId && !cancelled || jobBusy) && (
          <div className="flex justify-end">
            <button onClick={() => setConfirmCancel(true)}
              className="px-3 py-1.5 rounded-md border border-red-300 text-red-700 text-sm hover:bg-red-50">Cancel run</button>
          </div>
        )}

        {cancelled && (
          <div className="rounded-lg border border-slate-300 bg-slate-100 p-4 text-sm flex items-center justify-between">
            <span className="text-slate-700">This run was cancelled. Nothing was deleted.</span>
            <button onClick={() => api.v2Restore(run.run_id).then(() => { loadRuns(); loadRun(run.run_id); }).catch((e) => setError(e.message))}
              className="px-3 py-1.5 rounded-md bg-slate-700 text-white text-sm">Restore run</button>
          </div>
        )}

        {job && (
          <div className={`rounded-lg border p-4 text-sm ${job.status === "error" ? "border-red-300 bg-red-50" : "border-slate-200 bg-white"}`}>
            <p className="font-medium text-slate-700">
              {job.kind} — {busy ? "running… (the AI and Google calls can take a few minutes)" : job.status}
            </p>
            {job.status === "error" && <p className="text-red-700 mt-1 whitespace-pre-wrap">{job.error}</p>}
            {job.status === "error" && job.run_id && <p className="text-xs text-slate-500 mt-1">Run id: {job.run_id}</p>}
            {job.status === "error" && <CostPanel cost={job.cost} title="Cost before the failure" />}
          </div>
        )}

        {!runId && (
          <div className="bg-white border border-slate-200 rounded-lg p-5 space-y-4">
            <h2 className="text-lg font-semibold text-slate-800">New AIG v2 run</h2>
            <div>
              <label className="block text-sm text-slate-600 mb-1">
                Filled intake template (.docx) — <a className="text-blue-600" href={api.v2TemplateUrl()}>download blank template</a>
              </label>
              {intake ? (
                <FileList files={[intake]} onRemove={() => setIntake(null)} />
              ) : (
                <input key="intake" type="file" accept=".docx" disabled={busy} onChange={(e) => { setIntake(e.target.files?.[0] ?? null); e.target.value = ""; }} />
              )}
            </div>
            <div>
              <label className="block text-sm text-slate-600 mb-1">Attachments (itinerary, vouchers, tickets…)</label>
              <AttachmentPicker files={attachments} setFiles={setAttachments} disabled={!!busy} />
            </div>
            <button
              disabled={busy || (!intake && attachments.length === 0)}
              onClick={() => launch(() => api.v2Start(intake, attachments))}
              className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium disabled:opacity-40"
            >{busy ? "Reading inputs… (this can take a minute)" : "Read inputs & list questions"}</button>
          </div>
        )}

        {run && (
          <>
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <h2 className="text-lg font-semibold text-slate-800">{run.title || run.run_id}</h2>
              <p className="text-xs text-slate-400 font-mono">{run.run_id}</p>
              <p className="text-sm text-slate-600 mt-2">
                {run.trip.days?.length ?? 0} days · {run.trip.hotels?.length ?? 0} stays · {run.trip.transport?.length ?? 0} transport legs · {run.trip.trip_scope}
              </p>
            </div>

            {!built && !cancelled && (
              <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
                <h3 className="text-sm font-semibold text-slate-700">
                  Pre-flight questions ({run.questions.length - unanswered.length}/{run.questions.length} answered)
                </h3>
                {run.questions.length === 0 && <p className="text-sm text-slate-400">No questions.</p>}
                {run.questions.map((q: any) => (
                  <div key={q.id}>
                    <label className="block text-sm text-slate-700">{q.text}</label>
                    {q.options?.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-1">
                        {q.options.map((o: string) => (
                          <button key={o} onClick={() => setAnswers({ ...answers, [q.id]: o })}
                            className={`px-2 py-1 rounded border text-xs ${answers[q.id] === o ? "bg-blue-600 text-white border-blue-600" : "border-slate-300 text-slate-600"}`}>{o}</button>
                        ))}
                      </div>
                    )}
                    <AnswerBox value={answers[q.id] ?? ""} onChange={(v) => setAnswers({ ...answers, [q.id]: v })}
                      placeholder={q.options?.length ? "or type your own" : "answer"} />
                  </div>
                ))}
                <button
                  disabled={busy || unanswered.length > 0}
                  onClick={() => launch(() => api.v2Plan(run.run_id, answers))}
                  className="mr-2 px-4 py-2 rounded-md border border-blue-600 text-blue-700 text-sm font-medium disabled:opacity-40"
                  title="Optional: plan the guide first (no AI writing) and fix restaurant gaps by pasting Google Maps links"
                >Plan restaurants first (optional)</button>
                {(run.plan_items ?? []).length > 0 && (
                  <div className="border-t border-slate-200 pt-3 space-y-3">
                    <h3 className="text-sm font-semibold text-slate-700">
                      Needs attention before writing ({run.plan_items.length}) — optional; paste a Google Maps link of ONE place, or leave blank / Skip, then press Plan again to apply
                    </h3>
                    {(run.plan_failed ?? []).map((f: string) => <p key={f} className="text-xs text-red-700">NOT USED: {f}</p>)}
                    {run.plan_items.map((q: any) => (
                      <div key={q.id}>
                        <label className="block text-sm text-slate-700">{q.text}</label>
                        <AnswerBox value={answers[q.id] ?? ""} onChange={(v) => setAnswers({ ...answers, [q.id]: v })}
                          placeholder="https://maps.app.goo.gl/... or Skip" />
                      </div>
                    ))}
                  </div>
                )}
                <button
                  disabled={busy || unanswered.length > 0}
                  onClick={() => launch(() => api.v2Build(run.run_id, answers))}
                  className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium disabled:opacity-40"
                >Build guide</button>
              </div>
            )}

            <CostPanel cost={run.cost} title="Cost so far (latest step)" />

            {run.cost_history.length > 1 && (
              <details className="bg-white border border-slate-200 rounded-lg p-4 text-sm">
                <summary className="cursor-pointer text-slate-700">Cost history ({run.cost_history.length} steps)</summary>
                {run.cost_history.map((h: any, i: number) => (
                  <div key={i} className="flex justify-between text-xs text-slate-500 mt-1">
                    <span>{h.command} · {h.at.slice(0, 19).replace("T", " ")}</span>
                    <span>AI {usd(h.cost.ai?.total_usd)} · Google {usd(h.cost.google?.total_usd)} · total {usd(h.cost.total_usd)}</span>
                  </div>
                ))}
              </details>
            )}

            {built && (
              <>
                <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-2">
                  <h3 className="text-sm font-semibold text-slate-700">
                    QC: {run.qc ? (run.qc.passed ? "PASS" : "FAIL") : "—"}
                    {run.qc && ` · ${run.qc.findings?.length ?? 0} findings`}
                  </h3>
                  {(run.qc?.findings ?? []).slice(0, 30).map((f: any, i: number) => (
                    <p key={i} className={`text-xs ${f.severity === "error" ? "text-red-700" : "text-slate-600"}`}>
                      • {f.day == null ? "General" : `Day ${f.day}`} [{f.severity}] {f.rule}: {f.message}
                    </p>
                  ))}
                </div>

                <div className="bg-white border border-slate-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-slate-700 mb-2">Downloads</h3>
                  <div className="flex flex-wrap gap-2">
                    {run.files.map((n: string) => (
                      <a key={n} href={api.v2FileUrl(run.run_id, n)} className="px-2 py-1 rounded border border-slate-300 text-xs text-blue-600 hover:bg-blue-50">{n}</a>
                    ))}
                  </div>
                </div>

                <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-slate-700">Rewrite parts (old outputs are kept as .vN)</h3>
                  <input className="w-full border border-slate-300 rounded px-2 py-1 text-sm" placeholder={`Day numbers, e.g. 2, 4 (1–${run.day_count})`}
                    value={days} onChange={(e) => setDays(e.target.value)} />
                  <div className="flex flex-wrap gap-2">
                    {run.regen_sections.map((s: string) => (
                      <label key={s} className="text-xs text-slate-600 flex items-center gap-1">
                        <input type="checkbox" checked={sections.includes(s)}
                          onChange={(e) => setSections(e.target.checked ? [...sections, s] : sections.filter((x) => x !== s))} />{s}
                      </label>
                    ))}
                  </div>
                  <button
                    disabled={busy || (!days.trim() && sections.length === 0)}
                    onClick={() => launch(() => api.v2Regenerate(run.run_id,
                      days.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n)), sections))}
                    className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium disabled:opacity-40"
                  >Regenerate</button>
                </div>

                <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-2">
                  <h3 className="text-sm font-semibold text-slate-700">Re-run QC on an edited guide</h3>
                  <input type="file" accept=".docx" disabled={busy}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) launch(() => api.v2Qc(run.run_id, f)); e.target.value = ""; }} />
                </div>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}
