/** Small display helpers shared by the dashboards. */
export function fmtTime(t: string): string {
  const [h, m] = t.split(':').map(Number);
  const ampm = h >= 12 ? 'PM' : 'AM';
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${ampm}`;
}

export function fmtDate(d: string): string {
  const [y, m, day] = d.split('-').map(Number);
  return new Date(y, m - 1, day).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

export function firstName(name: string): string {
  return name.replace(/^Dr\.?\s+/i, '').split(' ')[0] || name;
}

export function scoreLabel(score: number): { label: string; cls: string } {
  if (score >= 80) return { label: 'Critical', cls: 'text-danger bg-danger-bg' };
  if (score >= 60) return { label: 'Urgent', cls: 'text-warning bg-warning-bg' };
  if (score >= 40) return { label: 'Moderate', cls: 'text-info bg-info-bg' };
  return { label: 'Routine', cls: 'text-success bg-success-bg' };
}

/** Debounce helper for the live AI preview while someone types symptoms. */
export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  let t: ReturnType<typeof setTimeout>;
  return (...a: A) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
