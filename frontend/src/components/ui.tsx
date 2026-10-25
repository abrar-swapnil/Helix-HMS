/** Shared primitive UI components used across all dashboards. */

export function PageHeader({
  title, subtitle, children,
}: {
  title: string; subtitle: string; children?: React.ReactNode;
}) {
  return (
    <div className="bg-card border-b border-rule px-8 py-5 flex items-center justify-between shrink-0">
      <div>
        <h1 className="text-xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{title}</h1>
        <p className="text-ink-muted text-sm mt-0.5">{subtitle}</p>
      </div>
      {children && <div className="flex items-center gap-3">{children}</div>}
    </div>
  );
}

export function StatCard({
  label, value, sub, icon, bg,
}: {
  label: string; value: number | string; sub?: string; icon: React.ReactNode; bg: string;
}) {
  return (
    <div className="bg-card rounded-2xl border border-rule p-5 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${bg}`}>{icon}</div>
      <div>
        <div className="text-2xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{value}</div>
        <div className="text-xs font-medium text-ink-muted">{label}</div>
        {sub && <div className="text-xs text-ink-faint mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    available: 'text-success bg-success-bg',
    busy: 'text-warning bg-warning-bg',
    unavailable: 'text-danger bg-danger-bg',
    scheduled: 'text-teal bg-teal-muted',
    completed: 'text-success bg-success-bg',
    cancelled: 'text-ink-muted bg-surface',
  };
  return (
    <span className={`text-xs font-medium px-2.5 py-1 rounded-full capitalize ${map[status] ?? 'text-ink-muted bg-surface'}`}>
      {status}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    available: 'bg-success',
    busy: 'bg-warning',
    unavailable: 'bg-danger',
  };
  return <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${map[status] ?? 'bg-ink-faint'}`} />;
}

export function Modal({
  title, onClose, onSave, saveLabel = 'Save', children, error, busy, wide,
}: {
  title: string; onClose: () => void; onSave: () => void; saveLabel?: string; children: React.ReactNode;
  /** message from the server (e.g. "That slot is taken") shown above the buttons */
  error?: string;
  /** disables Save while a request is in flight */
  busy?: boolean;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className={`bg-card rounded-2xl border border-rule shadow-xl w-full ${wide ? 'max-w-2xl' : 'max-w-md'} max-h-[92vh] flex flex-col`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-rule">
          <h3 className="font-semibold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{title}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ink-muted"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="px-6 py-5 space-y-4 overflow-y-auto">{children}</div>
        {error && <div className="mx-6 mb-3 text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
        <div className="flex gap-3 px-6 py-4 border-t border-rule">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-xl border border-rule text-sm text-ink-muted hover:bg-surface transition-colors">Cancel</button>
          <button onClick={onSave} disabled={busy} className="flex-1 py-2.5 rounded-xl bg-teal hover:bg-teal-light disabled:opacity-60 text-white text-sm font-medium transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
            {busy ? 'Please wait…' : saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function FormRow({
  label, value, onChange, placeholder, type = 'text', required,
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; required?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">{label}</label>
      <input
        type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} required={required}
        className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm placeholder:text-ink-faint focus:border-teal transition-colors"
      />
    </div>
  );
}

/** Simple toast-style notification. Mount at root level and pass show/message. */
export function Toast({ show, message, variant = 'success' }: { show: boolean; message: string; variant?: 'success' | 'danger' | 'warning' | 'info' }) {
  const colors: Record<string, string> = {
    success: 'bg-success text-white',
    danger: 'bg-danger text-white',
    warning: 'bg-warning text-white',
    info: 'bg-navy text-white',
  };
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-[70] px-5 py-3 rounded-xl shadow-xl text-sm font-medium transition-all duration-300 ${colors[variant]} ${show ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'}`}
      style={{ fontFamily: 'var(--font-display)' }}>
      {message}
    </div>
  );
}
