import { useRef, useState } from 'react';
import { FileText, Upload, Trash2, Download, X, Loader2, Paperclip } from 'lucide-react';
import { api, errorMessage } from '../../lib/api';
import { useLiveQuery } from '../../lib/live';
import { fmtDate, fmtSize } from '../../lib/format';
import type { MedicalDoc } from '../../types';

interface Props {
  patientId: string;
  patientName: string;
  canUpload: boolean;
  onClose: () => void;
}

/** Medical records of one patient: the AI reads uploaded PDF / text files (and the typed note) for chronic conditions. */
export function RecordsPanel({ patientId, canUpload, compact }: { patientId: string; canUpload: boolean; compact?: boolean }) {
  const { data, loading, reload } = useLiveQuery(() => api.get<MedicalDoc[]>(`/patients/${patientId}/documents`), ['documents'], { pollMs: 60000 });
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const docs = data ?? [];

  const upload = async (file: File) => {
    setBusy(true); setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('notes', notes);
      await api.upload(`/patients/${patientId}/documents`, form);
      setNotes('');
      await reload();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  const remove = async (id: string) => {
    setError('');
    try { await api.del(`/patients/${patientId}/documents/${id}`); await reload(); } catch (e) { setError(errorMessage(e)); }
  };

  return (
    <div className="space-y-3">
      {canUpload && (
        <div className="rounded-xl border border-dashed border-rule bg-surface p-3.5 space-y-2.5">
          <div className="text-xs text-ink-muted leading-relaxed">
            Attach previous medical documents (PDF, TXT, PNG, JPG · max 5 MB). The AI reads them to understand chronic conditions and prioritise the queue safely.
          </div>
          <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional note, e.g. “known asthma, takes warfarin” (also read by the AI)"
            className="w-full bg-card border border-rule rounded-xl px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-teal transition-colors" />
          <input ref={fileRef} type="file" accept=".pdf,.txt,.md,.csv,.json,.png,.jpg,.jpeg" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); }} />
          <button onClick={() => fileRef.current?.click()} disabled={busy}
            className="flex items-center gap-2 bg-teal hover:bg-teal-light disabled:opacity-60 text-white text-xs font-semibold px-4 py-2.5 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} {busy ? 'Uploading…' : 'Upload document'}
          </button>
        </div>
      )}
      {error && <div className="text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
      {loading ? (
        <div className="text-xs text-ink-faint py-4 text-center">Loading records…</div>
      ) : docs.length === 0 ? (
        <div className="text-sm text-ink-faint text-center py-6">No medical documents on file{canUpload ? ' yet.' : '.'}</div>
      ) : (
        <ul className={`space-y-2 ${compact ? '' : 'max-h-80 overflow-y-auto pr-1'}`}>
          {docs.map(d => (
            <li key={d.id} className="flex items-start gap-3 bg-card border border-rule rounded-xl p-3">
              <div className="w-9 h-9 rounded-lg bg-teal-muted flex items-center justify-center shrink-0"><FileText size={16} className="text-teal" /></div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-ink truncate">{d.filename}</div>
                <div className="text-xs text-ink-faint">{fmtSize(d.size)} · {fmtDate(d.uploadedAt.slice(0, 10))}</div>
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {d.conditions.map(c => <span key={c} className="text-[11px] font-medium text-teal bg-teal-muted px-2 py-0.5 rounded-full">{c}</span>)}
                  {d.conditions.length === 0 && <span className="text-[11px] text-ink-faint">{d.textExtracted ? 'No chronic conditions detected' : 'No text could be read — add a note so the AI can use it'}</span>}
                </div>
                {d.notes && <div className="text-xs text-ink-muted mt-1 italic">“{d.notes}”</div>}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <a href={`/api/patients/${patientId}/documents/${d.id}/download`} className="p-1.5 rounded-lg text-ink-faint hover:text-teal hover:bg-teal-muted transition-colors" title="Download"><Download size={14} /></a>
                {canUpload && <button onClick={() => remove(d.id)} className="p-1.5 rounded-lg text-ink-faint hover:text-danger hover:bg-danger-bg transition-colors" title="Delete"><Trash2 size={14} /></button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function RecordsModal({ patientId, patientName, canUpload, onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-card rounded-2xl border border-rule shadow-xl w-full max-w-lg max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-rule">
          <div className="flex items-center gap-2 min-w-0">
            <Paperclip size={16} className="text-teal shrink-0" />
            <h3 className="font-semibold text-ink truncate" style={{ fontFamily: 'var(--font-display)' }}>Medical records · {patientName}</h3>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface transition-colors"><X size={16} className="text-ink-muted" /></button>
        </div>
        <div className="px-6 py-5 overflow-y-auto"><RecordsPanel patientId={patientId} canUpload={canUpload} /></div>
      </div>
    </div>
  );
}
