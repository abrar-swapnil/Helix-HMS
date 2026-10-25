/**
 * lib/api.ts - the ONLY place the frontend talks to the Python backend.
 *
 *  - every request goes to /api/... on the same origin (Vite proxies it in dev, the backend serves it in production)
 *  - the login cookie is HttpOnly, so no token is ever visible to JavaScript
 *  - mutating calls send `X-Requested-With: helix` (the backend rejects state changes without it - CSRF protection)
 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { 'X-Requested-With': 'helix' };
  let payload: BodyInit | undefined;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.');
  }
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event('helix:unauthorized'));   // session expired -> App shows the login page
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : res.statusText || 'Request failed');
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  del: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, undefined, form),
};

export const errorMessage = (e: unknown): string => (e instanceof Error ? e.message : 'Something went wrong.');

/** Streams the chatbot answer. Calls onDelta for every piece of text as it arrives. */
export async function streamChat(
  messages: { role: 'user' | 'assistant'; content: string }[],
  onMeta: (mode: 'ollama' | 'basic') => void,
  onDelta: (text: string) => void,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'helix' },
      body: JSON.stringify({ messages }),
      credentials: 'same-origin',
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the server.');
  }
  if (!res.ok || !res.body) {
    let msg = 'The assistant is unavailable right now.';
    try { msg = (await res.json()).detail ?? msg; } catch { /* keep default */ }
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try {
        const ev = JSON.parse(line);
        if (ev.type === 'meta') onMeta(ev.mode);
        else if (ev.type === 'delta') onDelta(ev.text);
      } catch { /* ignore a malformed line */ }
    }
  }
}
