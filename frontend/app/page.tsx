"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Doc = { id: number; title: string; status: string; pages: number | null };
type Source = { n: number; title: string; pages: string; snippet: string };
type Step = { tool: string; arguments: string };
type Msg = {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  steps?: Step[];
  complete?: boolean;
  error?: boolean;
};

function detail(d: unknown, fallback: string) {
  const v = (d as { detail?: unknown })?.detail;
  return typeof v === "string" ? v : fallback;
}

// Renders markdown; turns [1] markers into buttons that open the source passage.
function Answer({ msg, onCite }: { msg: Msg; onCite: (s: Source) => void }) {
  const text = msg.text.replace(/\[(\d+)\]/g, "[$1](#cite-$1)");
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const n = href?.startsWith("#cite-") ? Number(href.slice(6)) : 0;
            const s = n ? msg.sources?.find((x) => x.n === n) : undefined;
            if (s)
              return (
                <button type="button" onClick={() => onCite(s)} title={`${s.title}, pages ${s.pages}`} className="cite">
                  {children}
                </button>
              );
            // Any other link is shown as plain text, never as a clickable link.
            return <span>{n ? `[${n}]` : children}</span>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default function Home() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"agent" | "basic">("agent");
  const [convId, setConvId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [offline, setOffline] = useState(false);
  const [open, setOpen] = useState<Source | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const loadDocs = useCallback(async () => {
    try {
      const r = await fetch(`${API}/documents`);
      if (!r.ok) throw new Error();
      setDocs(await r.json());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  // Poll while any document is still being processed.
  useEffect(() => {
    if (!docs.some((d) => d.status === "queued" || d.status === "processing")) return;
    const t = setInterval(loadDocs, 2000);
    return () => clearInterval(t);
  }, [docs, loadDocs]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  async function upload(file: File) {
    setNote(`Uploading ${file.name}…`);
    const body = new FormData();
    body.append("file", file);
    try {
      const r = await fetch(`${API}/documents`, { method: "POST", body });
      if (!r.ok) {
        setNote(detail(await r.json().catch(() => ({})), "Upload failed."));
        return;
      }
      setNote("");
      loadDocs();
    } catch {
      setNote("Could not reach the server.");
    }
  }

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setOpen(null);
    setMsgs((m) => [...m, { role: "user", text: question }]);
    try {
      const r = await fetch(`${API}/${mode === "agent" ? "agent" : "chat"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: convId,
          document_ids: selected ? [selected] : null,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(detail(d, "Request failed."));
      setConvId(d.conversation_id);
      setMsgs((m) => [
        ...m,
        { role: "assistant", text: d.answer, sources: d.sources, steps: d.steps, complete: d.complete },
      ]);
    } catch (e) {
      setMsgs((m) => [
        ...m,
        { role: "assistant", text: e instanceof Error ? e.message : "Something went wrong.", error: true },
      ]);
    }
    setBusy(false);
  }

  function newChat() {
    setMsgs([]);
    setConvId(null);
    setOpen(null);
  }

  const dot = (s: string) =>
    s === "ready" ? "bg-green-400" : s === "failed" ? "bg-red-400" : "bg-yellow-400";

  return (
    <main className="min-h-screen p-4 md:p-6">
      <div className="mx-auto grid max-w-5xl gap-6 md:grid-cols-[260px_1fr]">
        <aside className="space-y-6">
          <h1 className="text-lg font-semibold tracking-tight">Studybuddy</h1>

          <label className="btn-ghost block cursor-pointer border-dashed text-center focus-within:outline focus-within:outline-2">
            Upload a PDF
            <input
              type="file"
              accept="application/pdf"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
                e.target.value = "";
              }}
            />
          </label>
          {note && <p role="status" className="muted -mt-3 text-sm">{note}</p>}
          {offline && (
            <p role="alert" className="-mt-3 text-sm text-red-400">
              Can&apos;t reach the server. Is the backend running?
            </p>
          )}

          <div>
            <h2 className="muted mb-2 text-xs font-medium uppercase tracking-wider">Search in</h2>
            <ul className="space-y-1">
              <li>
                <button
                  type="button"
                  aria-pressed={selected === null}
                  onClick={() => setSelected(null)}
                  className={`chip ${selected === null ? "chip-active" : ""}`}
                >
                  All documents
                </button>
              </li>
              {docs.map((d) => (
                <li key={d.id}>
                  <button
                    type="button"
                    aria-pressed={selected === d.id}
                    onClick={() => setSelected(d.id)}
                    className={`chip ${selected === d.id ? "chip-active" : ""}`}
                  >
                    <span className="block truncate">{d.title}</span>
                    <span className="muted flex items-center gap-1.5 text-xs">
                      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot(d.status)}`} aria-hidden="true" />
                      {d.status}
                      {d.pages ? ` · ${d.pages} pages` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className="muted mb-2 text-xs font-medium uppercase tracking-wider">Mode</h2>
            <div className="flex gap-1 rounded-lg border border-[var(--line)] p-1">
              {(["agent", "basic"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={`flex-1 rounded-md px-3 py-1.5 text-sm ${
                    mode === m ? "bg-[var(--raised)] font-medium" : "muted hover:text-[var(--text)]"
                  }`}
                >
                  {m === "agent" ? "Agent" : "Basic"}
                </button>
              ))}
            </div>
          </div>

          <button type="button" onClick={newChat} className="btn-ghost w-full">
            New chat
          </button>
        </aside>

        <section className="panel flex h-[88vh] flex-col p-4">
          <div className="flex-1 space-y-6 overflow-y-auto pr-2" aria-live="polite">
            {msgs.length === 0 && (
              <p className="muted mt-16 text-center">
                Upload a PDF, then ask a question. Answers cite the pages they came from.
              </p>
            )}
            {msgs.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className="bubble-user">
                  {m.text}
                </div>
              ) : (
                <div key={i} className="max-w-[85ch] space-y-2 leading-relaxed">
                  {m.error ? <p className="text-red-400">{m.text}</p> : <Answer msg={m} onCite={setOpen} />}
                  {m.complete === false && (
                    <p className="text-sm text-yellow-400">
                      This answer was cut off. Ask me to continue or narrow the question.
                    </p>
                  )}
                  {m.steps && m.steps.length > 0 && (
                    <details className="muted text-sm">
                      <summary className="cursor-pointer">Agent steps ({m.steps.length})</summary>
                      <ul className="mt-1 list-disc pl-5">
                        {m.steps.map((s, j) => (
                          <li key={j}>
                            <code>{s.tool}</code> {s.arguments}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ),
            )}
            {busy && <p className="muted">{mode === "agent" ? "Thinking…" : "Searching…"}</p>}
            <div ref={end} />
          </div>

          {open && (
            <div className="source mt-3">
              <div className="mb-1 flex justify-between gap-2 font-medium">
                <span>
                  {open.title}, pages {open.pages}
                </span>
                <button type="button" onClick={() => setOpen(null)} aria-label="Close source" className="muted hover:text-[var(--text)]">
                  ✕
                </button>
              </div>
              <p className="muted max-h-32 overflow-y-auto whitespace-pre-wrap">{open.snippet}</p>
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="mt-3 flex gap-2"
          >
            <label htmlFor="q" className="sr-only">
              Your question
            </label>
            <input
              id="q"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={500}
              placeholder="Ask about your documents"
              className="flex-1 rounded-lg border border-[var(--line)] bg-[var(--bg)] px-4 py-2 placeholder:text-[var(--muted)]"
            />
            <button disabled={busy || !input.trim()} className="btn-primary">
              Ask
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}