export const API = '';

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(t.slice(0, 800) || `Request failed (${r.status})`);
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('event-stream')) return r;
  return r.json();
}

export const api = {
  health: () => req('/api/health'),
  status: () => req('/api/system/status'),
  dashboard: () => req('/api/dashboard'),
  docs: () => req('/api/documents'),
  upload: async (files: FileList | File[], onProgress?: (p: string) => void) => {
    const fd = new FormData();
    const arr = files instanceof FileList ? Array.from(files) : files;
    arr.forEach(f => fd.append('files', f));
    onProgress?.('Uploading & indexing…');
    return req('/api/documents/upload', { method: 'POST', body: fd });
  },
  reindex: (id: string) => req(`/api/documents/${id}/reindex`, { method: 'POST' }),
  delDoc: (id: string) => req(`/api/documents/${id}`, { method: 'DELETE' }),
  pdfUrl: (id: string) => `/api/documents/${id}/file`,
  convs: () => req('/api/conversations'),
  newConv: () => req('/api/conversations', { method: 'POST' }),
  delConv: (id: string) => req(`/api/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: string) => req(`/api/conversations/${id}/messages`),
  chat: (body: any) => req('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  explain: (body: any) => req('/api/study/explain', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  summarize: (body: any) => req('/api/study/summarize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  summaries: () => req('/api/study/summaries'),
  search: (q: string, doc_id?: string) => req(`/api/search?q=${encodeURIComponent(q)}${doc_id ? `&doc_id=${doc_id}` : ''}`),
  genFlash: (body: any) => req('/api/study/flashcards/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  flashcards: () => req('/api/study/flashcards'),
  markFlash: (id: string, status: string) => {
    const fd = new FormData(); fd.append('status', status);
    return req(`/api/study/flashcards/${id}/mark`, { method: 'POST', body: fd });
  },
  delFlash: (id: string) => req(`/api/study/flashcards/${id}`, { method: 'DELETE' }),
  genExam: (body: any) => req('/api/study/exam/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  submitExam: (body: any) => req('/api/study/exam/submit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  attempts: () => req('/api/study/exam/attempts'),
  saveConfig: (body: any) => req('/api/system/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
};

export type Citation = { filename: string; page: number; excerpt: string; doc_id: string; label: string; heading?: string };

export function pdfPageUrl(docId: string, page: number) {
  return `/api/documents/${docId}/file#page=${page}`;
}
