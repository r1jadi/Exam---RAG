import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, pdfPageUrl, Citation } from './api'

type Page = 'dashboard' | 'lectures' | 'tutor' | 'summaries' | 'flashcards' | 'exam' | 'settings'

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '◧' },
  { id: 'lectures', label: 'My Lectures', icon: '▤' },
  { id: 'tutor', label: 'AI Tutor', icon: '✦' },
  { id: 'summaries', label: 'Summaries', icon: '≡' },
  { id: 'flashcards', label: 'Flashcards', icon: '▦' },
  { id: 'exam', label: 'Exam Practice', icon: '✔' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
]

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('study-theme') || 'light')
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('study-theme', theme)
  }, [theme])
  return { theme, toggle: () => setTheme(t => (t === 'light' ? 'dark' : 'light')) }
}

function Citations({ cites }: { cites: Citation[] }) {
  if (!cites?.length) return null
  return (
    <div className="cites">
      {cites.map((c, i) => (
        <a key={i} className="cite" href={pdfPageUrl(c.doc_id, c.page)} target="_blank" rel="noreferrer" title={c.excerpt}>
          {c.label}
        </a>
      ))}
    </div>
  )
}

function SourcePanel({ cites }: { cites: Citation[] }) {
  if (!cites?.length) return <div className="empty">No sources yet. Ask something grounded in your lectures.</div>
  return (
    <div className="grid">
      {cites.map((c, i) => (
        <div key={i} className="card">
          <div style={{ fontSize: 13, fontWeight: 700 }}>
            <a href={pdfPageUrl(c.doc_id, c.page)} target="_blank" rel="noreferrer">{c.label}</a>
          </div>
          {c.heading && <div style={{ fontSize: 12, color: 'var(--muted)' }}>{c.heading}</div>}
          <div style={{ fontSize: 12.5, marginTop: 8, lineHeight: 1.55 }}>{c.excerpt}</div>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { theme, toggle } = useTheme()
  const [page, setPage] = useState<Page>('dashboard')
  const [status, setStatus] = useState<any>(null)
  const [statusErr, setStatusErr] = useState('')

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status()
      setStatus(s); setStatusErr('')
    } catch (e: any) { setStatusErr(e.message || 'Backend unreachable') }
  }, [])
  useEffect(() => { refreshStatus(); const t = setInterval(refreshStatus, 15000); return () => clearInterval(t) }, [refreshStatus])

  const ollamaOk = !!status?.ollama_available
  const ready = !!status?.chat_model_ready && !!status?.embed_model_ready

  return (
    <div>
      <div className="mobile-nav">
        {NAV.map(n => <button key={n.id} onClick={() => setPage(n.id)} style={page === n.id ? { borderColor: 'var(--accent)' } : {}}>{n.icon} {n.label}</button>)}
      </div>
      <div className="app">
        <aside className="sidebar">
          <div className="brand"><div className="logo">S</div><div><b>Study Assistant</b><small>100% local RAG</small></div></div>
          <nav className="nav grid">
            {NAV.map(n => <button key={n.id} className={page === n.id ? 'active' : ''} onClick={() => setPage(n.id)}><span>{n.icon}</span> {n.label}</button>)}
          </nav>
          <div className="local-badge">
            <span className={`dot ${ollamaOk && ready ? '' : 'off'}`} />
            {statusErr ? 'Backend unreachable' : ollamaOk ? (ready ? `Local AI ready · ${status?.chat_model}` : 'Ollama on · models missing') : 'Ollama offline'}
            <div style={{ marginTop: 6 }}>PDFs never leave this PC.</div>
          </div>
        </aside>
        <main className="main">
          <div className="topbar">
            <div><h1>{NAV.find(n => n.id === page)?.label}</h1><p>Ask in Albanian or English · answers cite your exact PDF pages.</p></div>
            <div className="row"><span className="pill">{status?.stats ? `${status.stats.indexed_documents} docs · ${status.stats.total_pages} pages` : '…'}</span><button className="btn small theme-toggle" onClick={toggle}>{theme === 'light' ? '☾ Dark' : '☀ Light'}</button></div>
          </div>
          {statusErr && <div className="alert bad">Backend not reachable at <kbd>127.0.0.1:8000</kbd>. Start it with <kbd>start_app.bat</kbd>. ({statusErr})</div>}
          {status && !status.ollama_available && <div className="alert bad"><b>Ollama is not running.</b><br />Install from ollama.com/download, then run <kbd>ollama serve</kbd>. Required models: <kbd>ollama pull {status.chat_model}</kbd> and <kbd>ollama pull {status.embed_model}</kbd>.</div>}
          {status?.ollama_available && (!status.chat_model_ready || !status.embed_model_ready) && (
            <div className="alert bad">Missing local model. Run:<br /><kbd>ollama pull {status.chat_model}</kbd><br /><kbd>ollama pull {status.embed_model}</kbd><br />Fallback that fits small RAM: <kbd>ollama pull {status.fallback_model}</kbd> (selectable in Settings).</div>
          )}
          {page === 'dashboard' && <Dashboard onGo={setPage} refresh={refreshStatus} />}
          {page === 'lectures' && <Lectures onChanged={refreshStatus} />}
          {page === 'tutor' && <Tutor />}
          {page === 'summaries' && <Summaries />}
          {page === 'flashcards' && <Flashcards />}
          {page === 'exam' && <Exam />}
          {page === 'settings' && <Settings status={status} refresh={refreshStatus} />}
        </main>
      </div>
    </div>
  )
}

/* ---------------- Dashboard ---------------- */
function Dashboard({ onGo, refresh }: { onGo: (p: Page) => void; refresh: () => void }) {
  const [data, setData] = useState<any>(null)
  useEffect(() => { api.dashboard().then(setData).catch(() => {}) }, [])
  if (!data) return <div className="card">Loading…</div>
  const cards = [
    ['Lectures indexed', data.indexed_documents],
    ['Pages processed', data.total_pages],
    ['Text chunks', data.total_chunks],
    ['Flashcards', data.flashcards_total],
    ['Known cards', data.flashcards_known],
    ['Exam attempts', data.exam_attempts],
  ]
  return (
    <div className="grid">
      <div className="grid kpi">{cards.map(([l, v]) => <div key={l} className="card"><b>{v}</b><span>{l}</span></div>)}</div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent activity</h3>
        {!data.recent_documents?.length && <div className="empty">No lectures yet. Upload your PDFs to begin.<br /><br /><button className="btn primary" onClick={() => onGo('lectures')}>Open My Lectures</button></div>}
        {!!data.recent_documents?.length && (
          <table className="table"><thead><tr><th>File</th><th>Status</th><th>Pages</th></tr></thead>
            <tbody>{data.recent_documents.map((d: any) => <tr key={d.id}><td>{d.filename}</td><td><span className={`pill ${d.status}`}>{d.status}</span></td><td>{d.page_count}</td></tr>)}</tbody>
          </table>
        )}
      </div>
      <div className="row">
        <button className="btn primary" onClick={() => onGo('tutor')}>Ask the AI Tutor</button>
        <button className="btn" onClick={() => onGo('exam')}>Practice for exam</button>
        <button className="btn" onClick={() => { refresh() }}>↻ Refresh</button>
      </div>
    </div>
  )
}

/* ---------------- Lectures ---------------- */
function Lectures({ onChanged }: { onChanged: () => void }) {
  const [docs, setDocs] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try { const d = await api.docs(); setDocs(d.documents || []) } catch (e: any) { setMsg(e.message) }
  }, [])
  useEffect(() => { load() }, [load])

  async function handleFiles(fl: FileList | null) {
    if (!fl?.length) return
    setBusy(true); setMsg(`Uploading ${fl.length} PDF(s) and indexing… (keeps working page-by-page)`)
    try {
      const r = await api.upload(fl)
      const errs = (r.results || []).filter((x: any) => x.error).map((x: any) => `${x.filename}: ${x.error}`)
      const dups = (r.results || []).filter((x: any) => x.duplicate).length
      setMsg(errs.length ? 'Issues: ' + errs.join(' | ') : `Done. ${r.results.length - dups} new, ${dups} duplicate(s) skipped.`)
      await load(); onChanged()
    } catch (e: any) { setMsg('Upload failed: ' + e.message) }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const shown = useMemo(() => docs.filter(d => !filter || d.filename.toLowerCase().includes(filter.toLowerCase())), [docs, filter])

  return (
    <div className="grid">
      <div className="drop" onClick={() => fileRef.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); handleFiles(e.dataTransfer.files) }}>
        <b>Drag & drop PDFs here</b> or click to choose multiple files
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>~30 PDFs · 1,500 pages OK · duplicates detected by file hash · originals kept locally</div>
        <input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={e => handleFiles(e.target.files)} />
      </div>
      {msg && <div className="alert">{msg}</div>}
      <div className="row">
        <input placeholder="Filter lectures…" value={filter} onChange={e => setFilter(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn" disabled={busy} onClick={load}>↻ Reload</button>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="table">
          <thead><tr><th>Document</th><th>Pages</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {shown.map(d => (
              <tr key={d.id}>
                <td><b>{d.filename}</b><div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.chunk_count} chunks · {(d.file_size / 1048576).toFixed(1)} MB{d.unreadable_pages?.length ? ` · ⚠ unreadable pages: ${d.unreadable_pages.join(',')}` : ''}{d.error ? ` · error: ${d.error.slice(0, 160)}` : ''}</div></td>
                <td>{d.page_count}</td>
                <td><span className={`pill ${d.status}`}>{d.status}</span></td>
                <td><div className="row">
                  <a className="btn small" href={api.pdfUrl(d.id)} target="_blank" rel="noreferrer">Open PDF</a>
                  <button className="btn small" onClick={async () => { setMsg('Re-indexing ' + d.filename + '…'); try { await api.reindex(d.id); setMsg('Re-indexed.'); load(); } catch (e: any) { setMsg(e.message) } }}>Re-index</button>
                  <button className="btn small" onClick={async () => { if (!confirm(`Delete ${d.filename}?`)) return; await api.delDoc(d.id); load(); onChanged() }}>Delete</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && <div className="empty">No documents. Upload lecture PDFs to build your local index.</div>}
      </div>
      <SearchBox />
    </div>
  )
}

function SearchBox() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Citation[]>([])
  const [err, setErr] = useState('')
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Semantic search (verify retrieval)</h3>
      <div className="row"><input style={{ flex: 1 }} placeholder="e.g. What is 3NF?" value={q} onChange={e => setQ(e.target.value)} /><button className="btn primary" onClick={async () => { setErr(''); try { const r = await api.search(q); setHits(r.chunks || []) } catch (e: any) { setErr(e.message) } }}>Search</button></div>
      {err && <div className="alert bad">{err}</div>}
      <div style={{ marginTop: 10 }}><SourcePanel cites={hits} /></div>
    </div>
  )
}

/* ---------------- Tutor ---------------- */
function Tutor() {
  const [convs, setConvs] = useState<any[]>([])
  const [cid, setCid] = useState<string>('')
  const [msgs, setMsgs] = useState<any[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [docs, setDocs] = useState<any[]>([])
  const [scope, setScope] = useState('') // '' = all, else doc id
  const [lang, setLang] = useState('auto')
  const [sideCites, setSideCites] = useState<Citation[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadConvs = useCallback(async () => { try { const c = await api.convs(); setConvs(c.conversations || []); if (!cid && c.conversations?.length) setCid(c.conversations[0].id) } catch { } }, [cid])
  useEffect(() => { loadConvs(); api.docs().then(d => setDocs(d.documents || [])).catch(() => {}) }, [loadConvs])
  useEffect(() => {
    if (!cid) { setMsgs([]); return }
    api.messages(cid).then(m => {
      setMsgs(m.messages || [])
      const last = [...(m.messages || [])].reverse().find(x => x.role === 'assistant' && x.citations?.length)
      setSideCites(last?.citations || [])
    }).catch(() => {})
  }, [cid])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  async function send(stream = true) {
    const text = input.trim()
    if (!text || busy) return
    setBusy(true); setInput('')
    const userMsg = { role: 'user', content: text, citations: [] }
    setMsgs(m => [...m, userMsg])
    const body = { message: text, conversation_id: cid || undefined, doc_ids: scope ? [scope] : undefined, language: lang }
    try {
      if (!stream) {
        const r = await api.chat(body)
        if (!cid) { setCid(r.conversation_id); loadConvs() }
        setMsgs(m => [...m, { role: 'assistant', content: r.answer, citations: r.citations }])
        setSideCites(r.citations || [])
      } else {
        const resp: Response = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        if (!resp.ok) throw new Error(await resp.text())
        const reader = resp.body!.getReader()
        const dec = new TextDecoder()
        let buf = '', acc = '', myCid = cid, cites: Citation[] = []
        // placeholder assistant msg
        setMsgs(m => [...m, { role: 'assistant', content: '', citations: [] }])
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const lines = buf.split('\n'); buf = lines.pop() || ''
          for (const ln of lines) {
            const t = ln.trim()
            if (!t.startsWith('data:')) continue
            const payload = t.slice(5).trim()
            if (payload === '[DONE]') continue
            try {
              const obj = JSON.parse(payload)
              const delta: string = obj.delta || ''
              if (delta.startsWith('__meta__:')) {
                const meta = JSON.parse(delta.slice(9))
                myCid = meta.conversation_id || myCid
                cites = meta.citations || []
              } else if (delta) {
                acc += delta
                const snapshot = acc
                setMsgs(m => { const c = [...m]; c[c.length - 1] = { role: 'assistant', content: snapshot, citations: cites }; return c })
              }
            } catch { }
          }
        }
        if (!cid && myCid) { setCid(myCid); loadConvs() }
        setSideCites(cites)
        setMsgs(m => { const c = [...m]; c[c.length - 1] = { role: 'assistant', content: acc, citations: cites }; return c })
      }
    } catch (e: any) {
      setMsgs(m => [...m, { role: 'assistant', content: '⚠ ' + (e.message || 'Failed').slice(0, 600), citations: [] }])
    } finally { setBusy(false) }
  }

  async function explainConcept() {
    const topic = input.trim() || 'the hardest concept in these lectures'
    setBusy(true)
    try {
      const r = await api.explain({ topic, doc_ids: scope ? [scope] : undefined, language: lang })
      setMsgs(m => [...m, { role: 'user', content: `Explain progressively: ${topic}` }, { role: 'assistant', content: r.answer, citations: r.citations }])
      setSideCites(r.citations || []); setInput('')
    } catch (e: any) { setMsgs(m => [...m, { role: 'assistant', content: '⚠ ' + e.message }]) }
    finally { setBusy(false) }
  }

  return (
    <div className="chat-wrap">
      <div>
        <div className="toolbar">
          <select value={cid} onChange={e => setCid(e.target.value)}><option value="">— select chat —</option>{convs.map(c => <option key={c.id} value={c.id}>{c.title?.slice(0, 40)}</option>)}</select>
          <button className="btn small" onClick={async () => { const c = await api.newConv(); setCid(c.id); setMsgs([]); loadConvs() }}>+ New</button>
          {cid && <button className="btn small" onClick={async () => { await api.delConv(cid); setCid(''); setMsgs([]); loadConvs() }}>Delete</button>}
          <select value={scope} onChange={e => setScope(e.target.value)}><option value="">All lectures</option>{docs.filter(d => d.status === 'ready').map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select>
          <select value={lang} onChange={e => setLang(e.target.value)}><option value="auto">Auto (AL/EN)</option><option value="Albanian">Albanian</option><option value="English">English</option></select>
        </div>
        <div className="card" style={{ minHeight: 380 }}>
          {!msgs.length && <div className="empty">Ask anything about your lectures.<br />Example: <i>Shpjego normalizimin me shembuj</i> · <i>Summarize lecture 4 in 5 bullets</i></div>}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="role">{m.role === 'user' ? 'You' : '● Local tutor'}</div>
              <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || (busy && i === msgs.length - 1 ? '…' : '')}</ReactMarkdown></div>
              {m.role === 'assistant' && m.content && (
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn small" onClick={() => navigator.clipboard.writeText(m.content)}>⧉ Copy</button>
                </div>
              )}
              {m.role === 'assistant' && <Citations cites={m.citations} />}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <textarea value={input} onChange={e => setInput(e.target.value)} placeholder="Ask in Albanian or English… (Enter to send, Shift+Enter newline)" onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(true) } }} />
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={busy} onClick={() => send(true)}>{busy ? 'Thinking locally…' : 'Send (streaming)'}</button>
          <button className="btn" disabled={busy} onClick={() => send(false)}>Send (no stream)</button>
          <button className="btn" disabled={busy} onClick={explainConcept}>Explain a concept</button>
        </div>
      </div>
      <div>
        <div className="card"><h3 style={{ marginTop: 0 }}>Sources</h3><SourcePanel cites={sideCites} /></div>
      </div>
    </div>
  )
}

/* ---------------- Summaries ---------------- */
function Summaries() {
  const [docs, setDocs] = useState<any[]>([])
  const [sel, setSel] = useState('')
  const [topic, setTopic] = useState('')
  const [lang, setLang] = useState('auto')
  const [out, setOut] = useState<any>(null)
  const [past, setPast] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.docs().then(d => setDocs(d.documents || [])).catch(() => {}); api.summaries().then(s => setPast(s.summaries || [])).catch(() => {}) }, [])
  const selDoc = docs.find(d => d.id === sel)
  async function gen() {
    setBusy(true); setOut(null)
    try {
      const r = await api.summarize({ doc_ids: sel ? [sel] : undefined, filename: selDoc && !topic ? selDoc.filename : undefined, topic: topic || undefined, language: lang })
      setOut(r); api.summaries().then(s => setPast(s.summaries || [])).catch(() => {})
    } catch (e: any) { setOut({ error: e.message }) }
    finally { setBusy(false) }
  }
  return (
    <div className="grid">
      <div className="card">
        <div className="row">
          <select value={sel} onChange={e => setSel(e.target.value)}><option value="">All lectures (needs topic)</option>{docs.map(d => <option key={d.id} value={d.id}>{d.filename} ({d.page_count}p)</option>)}</select>
          <input style={{ flex: 1, minWidth: 200 }} placeholder="Optional topic across lectures…" value={topic} onChange={e => setTopic(e.target.value)} />
          <select value={lang} onChange={e => setLang(e.target.value)}><option value="auto">Auto</option><option value="Albanian">Albanian</option><option value="English">English</option></select>
          <button className="btn primary" disabled={busy || (!sel && !topic)} onClick={gen}>{busy ? 'Summarizing…' : 'Generate summary'}</button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Honest coverage: the summary states exactly which material was used — never claims full-lecture coverage from partial chunks.</div>
      </div>
      {out && <div className="card">{out.error ? <div className="alert bad">{out.error}</div> : (<><h3 style={{ marginTop: 0 }}>{out.title}</h3><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{out.summary}</ReactMarkdown></div><div className="alert">{out.coverage}</div><Citations cites={out.citations} /></>)}</div>}
      <div className="card"><h3 style={{ marginTop: 0 }}>Saved summaries</h3>{!past.length ? <div className="empty">None yet.</div> : past.map(s => <div key={s.id} style={{ borderTop: '1px solid var(--line)', padding: '8px 0' }}><b>{s.title}</b><div style={{ fontSize: 12, color: 'var(--muted)' }}>{new Date(s.created_at * 1000).toLocaleString()}</div></div>)}</div>
    </div>
  )
}

/* ---------------- Flashcards ---------------- */
function Flashcards() {
  const [docs, setDocs] = useState<any[]>([])
  const [sel, setSel] = useState('')
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(10)
  const [cards, setCards] = useState<any[]>([])
  const [flipped, setFlipped] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const load = useCallback(async () => { try { const r = await api.flashcards(); setCards(r.flashcards || []) } catch { } }, [])
  useEffect(() => { load(); api.docs().then(d => setDocs(d.documents || [])).catch(() => {}) }, [load])
  async function gen() {
    setBusy(true); setMsg('')
    try {
      const selDoc = docs.find(d => d.id === sel)
      const r = await api.genFlash({ doc_ids: sel ? [sel] : undefined, filename: selDoc && !topic ? selDoc.filename : undefined, topic: topic || undefined, count })
      setMsg(`Generated ${r.flashcards.length} cards.`)
      load()
    } catch (e: any) { setMsg('Failed: ' + e.message) }
    finally { setBusy(false) }
  }
  const known = cards.filter(c => c.status === 'known').length
  return (
    <div className="grid">
      <div className="card"><div className="row">
        <select value={sel} onChange={e => setSel(e.target.value)}><option value="">All lectures</option>{docs.map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select>
        <input placeholder="Topic (optional)" value={topic} onChange={e => setTopic(e.target.value)} />
        <select value={count} onChange={e => setCount(Number(e.target.value))}>{[5, 10, 15, 20, 30].map(n => <option key={n} value={n}>{n} cards</option>)}</select>
        <button className="btn primary" disabled={busy} onClick={gen}>{busy ? 'Generating…' : 'Generate'}</button>
        <span className="pill">{known}/{cards.length} known</span>
      </div>{msg && <div className="alert">{msg}</div>}</div>
      <div className="flash-grid">
        {cards.map(c => (
          <div key={c.id} className="card flash">
            <div className="body"><b>Q:</b> {c.front}<br /><br />{flipped[c.id] ? (<><b>A:</b> {c.back}<div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>{c.source}</div></>) : <span style={{ color: 'var(--muted)' }}>Tap Reveal…</span>}</div>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn small" onClick={() => setFlipped(f => ({ ...f, [c.id]: !f[c.id] }))}>{flipped[c.id] ? 'Hide' : 'Reveal'}</button>
              <button className="btn small" onClick={async () => { await api.markFlash(c.id, 'known'); load() }}>✓ Known</button>
              <button className="btn small" onClick={async () => { await api.markFlash(c.id, 'difficult'); load() }}>★ Hard</button>
              <button className="btn small" onClick={async () => { await api.delFlash(c.id); load() }}>✕</button>
            </div>
            <span className="pill" style={{ marginTop: 8, alignSelf: 'flex-start' }}>{c.status}</span>
          </div>
        ))}
      </div>
      {!cards.length && <div className="empty">No flashcards yet — generate some from your lectures.</div>}
    </div>
  )
}

/* ---------------- Exam ---------------- */
function Exam() {
  const [docs, setDocs] = useState<any[]>([])
  const [sel, setSel] = useState('')
  const [topic, setTopic] = useState('')
  const [count, setCount] = useState(8)
  const [diff, setDiff] = useState('medium')
  const [mode, setMode] = useState<'practice' | 'mock'>('practice')
  const [qs, setQs] = useState<any[]>([])
  const [aid, setAid] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [result, setResult] = useState<any>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [idx, setIdx] = useState(0) // mock navigation
  const [attempts, setAttempts] = useState<any[]>([])
  const [timeLeft, setTimeLeft] = useState<number | null>(null)

  useEffect(() => { api.docs().then(d => setDocs(d.documents || [])).catch(() => {}); api.attempts().then(a => setAttempts(a.attempts || [])).catch(() => {}) }, [])
  useEffect(() => {
    if (timeLeft === null || timeLeft <= 0) return
    const t = setTimeout(() => setTimeLeft(v => (v === null ? v : v - 1)), 1000)
    return () => clearTimeout(t)
  }, [timeLeft])

  async function gen() {
    setBusy(true); setResult(null); setAnswers({}); setIdx(0)
    try {
      const selDoc = docs.find(d => d.id === sel)
      const r = await api.genExam({ doc_ids: sel ? [sel] : undefined, filename: selDoc && !topic ? selDoc.filename : undefined, topic: topic || undefined, count, difficulty: diff })
      setQs(r.questions || []); setAid(r.attempt_id); setNote(r.note || '')
      if (mode === 'mock') setTimeLeft((r.questions || []).length * 90)
    } catch (e: any) { setNote('Failed: ' + e.message) }
    finally { setBusy(false) }
  }
  async function submit() {
    try {
      const r = await api.submitExam({ attempt_id: aid, answers })
      setResult(r); setTimeLeft(null)
      api.attempts().then(a => setAttempts(a.attempts || [])).catch(() => {})
    } catch (e: any) { setNote('Submit failed: ' + e.message) }
  }
  const fbByIdx = (result?.feedback || []).reduce((m: any, f: any) => ({ ...m, [f.index]: f }), {} as any)
  const cur = qs[idx]

  return (
    <div className="grid">
      <div className="card"><div className="row">
        <select value={mode} onChange={e => setMode(e.target.value as any)}><option value="practice">Practice quiz</option><option value="mock">Mock exam (timed, navigable)</option></select>
        <select value={sel} onChange={e => setSel(e.target.value)}><option value="">Entire course</option>{docs.map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select>
        <input placeholder="Topic (optional)" value={topic} onChange={e => setTopic(e.target.value)} />
        <select value={count} onChange={e => setCount(Number(e.target.value))}>{[5, 8, 10, 12, 15, 20].map(n => <option key={n} value={n}>{n} Qs</option>)}</select>
        <select value={diff} onChange={e => setDiff(e.target.value)}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select>
        <button className="btn primary" disabled={busy} onClick={gen}>{busy ? 'Building…' : mode === 'mock' ? 'Start mock exam' : 'Generate quiz'}</button>
      </div>{note && <div className="alert">{note}</div>}
        {timeLeft !== null && qs.length > 0 && !result && <div className="alert">⏱ {Math.floor(timeLeft / 60)}:{String(timeLeft % 60).padStart(2, '0')} remaining</div>}
      </div>

      {!!qs.length && !result && mode === 'practice' && (
        <div className="card">
          {qs.map((q, i) => (
            <div key={i} style={{ borderBottom: '1px solid var(--line)', padding: '12px 0' }}>
              <b>Q{i + 1}. {q.question}</b> <span className="pill">{q.type}</span> {q.source && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{q.source}</span>}
              {q.type === 'mcq' && (q.options || []).map((o: string, j: number) => (
                <label key={j} className={`exam-opt ${answers[String(i)] === o[0] || answers[String(i)] === o ? 'sel' : ''}`}>
                  <input type="radio" name={`q${i}`} checked={answers[String(i)] === o[0] || answers[String(i)] === o} onChange={() => setAnswers(a => ({ ...a, [String(i)]: o[0] }))} /> {o}
                </label>
              ))}
              {q.type !== 'mcq' && <textarea value={answers[String(i)] || ''} onChange={e => setAnswers(a => ({ ...a, [String(i)]: e.target.value }))} placeholder="Your answer…" />}
            </div>
          ))}
          <div className="row" style={{ marginTop: 12 }}><button className="btn primary" onClick={submit}>Submit & grade</button></div>
        </div>
      )}

      {!!qs.length && !result && mode === 'mock' && cur && (
        <div className="card">
          <div className="row"><span className="pill">Question {idx + 1}/{qs.length}</span>{cur.source && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{cur.source}</span>}</div>
          <h3>{cur.question}</h3>
          {cur.type === 'mcq' && (cur.options || []).map((o: string, j: number) => (
            <label key={j} className={`exam-opt ${answers[String(idx)] === o[0] ? 'sel' : ''}`}>
              <input type="radio" name="mockq" checked={answers[String(idx)] === o[0]} onChange={() => setAnswers(a => ({ ...a, [String(idx)]: o[0] }))} /> {o}
            </label>
          ))}
          {cur.type !== 'mcq' && <textarea value={answers[String(idx)] || ''} onChange={e => setAnswers(a => ({ ...a, [String(idx)]: e.target.value }))} placeholder="Your answer…" />}
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={idx === 0} onClick={() => setIdx(i => i - 1)}>← Prev</button>
            <button className="btn" disabled={idx >= qs.length - 1} onClick={() => setIdx(i => i + 1)}>Next →</button>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>{Object.keys(answers).length}/{qs.length} answered</span>
            <button className="btn primary" onClick={submit}>Submit exam</button>
          </div>
          <div className="row" style={{ marginTop: 8 }}>{qs.map((_, i) => <button key={i} className="btn small" style={i === idx ? { borderColor: 'var(--accent)' } : answers[String(i)] ? { background: 'var(--panel2)' } : {}} onClick={() => setIdx(i)}>{i + 1}</button>)}</div>
        </div>
      )}

      {result && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Score: {result.score}/{result.total}</h3>
          {(result.feedback || []).map((f: any) => (
            <div key={f.index} className="alert" style={{ borderColor: f.correct ? '#bbf7d0' : '#fecaca' }}>
              <b>Q{f.index + 1}: {f.correct ? '✓ Correct' : '✕ Wrong'}</b><br />
              Your answer: {f.given || '—'}<br />Expected: {f.expected}<br />{f.explanation}<br />
              {f.source && <span style={{ fontSize: 12 }}>{f.source}</span>}
            </div>
          ))}
          <button className="btn" onClick={() => { setQs([]); setResult(null) }}>New quiz</button>
        </div>
      )}

      <div className="card"><h3 style={{ marginTop: 0 }}>Past attempts (saved locally)</h3>
        {!attempts.length ? <div className="empty">No attempts yet.</div> :
          <table className="table"><thead><tr><th>Date</th><th>Kind</th><th>Score</th></tr></thead><tbody>
            {attempts.map(a => <tr key={a.id}><td>{new Date(a.created_at * 1000).toLocaleString()}</td><td>{a.kind}</td><td>{a.score}/{a.total}</td></tr>)}
          </tbody></table>}
      </div>
    </div>
  )
}

/* ---------------- Settings ---------------- */
function Settings({ status, refresh }: { status: any; refresh: () => void }) {
  const [model, setModel] = useState(status?.chat_model || 'qwen3.5:9b')
  const [topk, setTopk] = useState(status?.top_k || 6)
  const [ctx, setCtx] = useState(status?.num_ctx || 8192)
  const [msg, setMsg] = useState('')
  useEffect(() => { if (status) { setModel(status.chat_model); setTopk(status.top_k); setCtx(status.num_ctx) } }, [status])
  return (
    <div className="grid">
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Local AI models (Ollama)</h3>
        <div style={{ fontSize: 13, lineHeight: 1.7 }}>
          <div>Server: <kbd>{status?.ollama_host}</kbd> — {status?.ollama_available ? 'running ✓' : 'not running ✕'}</div>
          <div>Chat model: <kbd>{status?.chat_model}</kbd> {status?.chat_model_ready ? '✓ installed' : '✕ missing'}</div>
          <div>Embedding model: <kbd>{status?.embed_model}</kbd> {status?.embed_model_ready ? '✓ installed' : '✕ missing'}</div>
          <div>Installed: {(status?.models_installed || []).join(', ') || '—'}</div>
          <div>RAM: {status?.ram_gb ? `${status.ram_gb} GB` : 'unknown'} · Vectors: {status?.vector_count} · Free disk: {status?.disk_free_gb} GB</div>
        </div>
        <div className="alert">Privacy: everything runs on <kbd>127.0.0.1</kbd>. No OpenAI/Anthropic/Gemini, no Pinecone/Supabase, no telemetry. PDFs, embeddings and chats stay in the <kbd>data/</kbd> folder.</div>
        <div className="alert">If the 9b model is too heavy for your 16 GB PC, install the fallback: <kbd>ollama pull {status?.fallback_model || 'qwen2.5:3b'}</kbd> then select it below.</div>
      </div>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Configuration</h3>
        <div className="row">
          <label>Chat model <input value={model} onChange={e => setModel(e.target.value)} style={{ width: 200 }} /></label>
          <label>Top-K <select value={topk} onChange={e => setTopk(Number(e.target.value))}>{[3, 4, 5, 6, 8, 10, 12].map(n => <option key={n} value={n}>{n} chunks</option>)}</select></label>
          <label>Context <select value={ctx} onChange={e => setCtx(Number(e.target.value))}>{[4096, 8192, 16384, 32768].map(n => <option key={n} value={n}>{n} tokens</option>)}</select></label>
          <button className="btn primary" onClick={async () => { try { await api.saveConfig({ chat_model: model, top_k: topk, num_ctx: ctx }); setMsg('Saved.'); refresh() } catch (e: any) { setMsg(e.message) } }}>Save</button>
        </div>
        {msg && <div className="alert">{msg}</div>}
      </div>
    </div>
  )
}
