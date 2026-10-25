import { useEffect, useState } from 'react';
import { Brain, Loader2 } from 'lucide-react';
import { api } from '../../lib/api';
import { scoreLabel } from '../../lib/format';
import type { TriagePreview } from '../../types';

interface Props {
  symptoms: string;
  age?: number | null;
  type?: 'general' | 'emergency';
  patientId?: string;
  phone?: string;
  doctorId?: string;
  /** called when the user clicks a suggested specialty chip (so the form can pre-filter its doctor list) */
  onPickSpecialty?: (specialty: string) => void;
  /** the specialty of the doctor the user picked - used to warn about a mismatch */
  selectedSpecialty?: string;
}

/**
 * Live, explainable AI triage preview. Sends the typed symptoms to the backend while the user types and shows
 * the score the XGBoost model would give, what it understood, the history it found in uploaded records,
 * and which specialty fits. Nothing is saved here.
 */
export default function AiPreview({ symptoms, age, type = 'general', patientId, phone, doctorId, onPickSpecialty, selectedSpecialty }: Props) {
  const [data, setData] = useState<TriagePreview | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const text = symptoms.trim();
    if (text.length < 3) { setData(null); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await api.post<TriagePreview>('/ai/triage-preview', {
          symptoms: text, age: age ?? null, type, patientId: patientId ? Number(patientId) : null, phone: phone ?? '', doctorId: doctorId ? Number(doctorId) : null,
        });
        setData(r);
      } catch { setData(null); } finally { setBusy(false); }
    }, 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symptoms, age, type, patientId, phone, doctorId]);

  if (symptoms.trim().length < 3) return null;
  if (!data) {
    return busy ? (
      <div className="flex items-center gap-2 text-xs text-ink-faint px-1"><Loader2 size={13} className="animate-spin" /> AI is reading the symptoms…</div>
    ) : null;
  }
  const { cls } = scoreLabel(data.healthScore);
  const understood = data.detected.length > 0;
  const mismatch = selectedSpecialty && data.suggestedSpecialties.length > 0 && !data.suggestedSpecialties.includes(selectedSpecialty);
  return (
    <div className="rounded-xl border border-rule bg-surface p-3.5 space-y-2.5">
      <div className="flex items-center gap-3">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center text-base font-bold shrink-0 ${cls}`} style={{ fontFamily: 'var(--font-display)' }}>
          {data.healthScore}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-ink" style={{ fontFamily: 'var(--font-display)' }}>
            <Brain size={13} className="text-teal" /> AI Health Score · <span className={`px-1.5 py-0.5 rounded-full ${cls}`}>{data.label}</span>
            {busy && <Loader2 size={11} className="animate-spin text-ink-faint" />}
          </div>
          <div className="text-xs text-ink-muted mt-0.5">
            {understood ? <>Detected: {data.detected.join(', ')}</> : 'Could not interpret this description — please add more detail (staff will review).'}
          </div>
        </div>
      </div>
      {data.historyFlags.length > 0 && (
        <div className="text-xs text-ink-muted">Medical history on file: <span className="font-medium text-ink">{data.historyFlags.join(', ')}</span></div>
      )}
      {data.suggestedSpecialties.length > 0 && (
        <div className="text-xs text-ink-muted flex flex-wrap items-center gap-1.5">
          Suggested specialty:
          {data.suggestedSpecialties.slice(0, 3).map(sp => {
            const available = data.availableSpecialties.includes(sp);
            return (
              <button key={sp} type="button" disabled={!onPickSpecialty || !available} onClick={() => onPickSpecialty?.(sp)}
                title={available ? 'Show doctors of this specialty' : 'No doctor of this specialty is available right now'}
                className={`px-2 py-0.5 rounded-full font-medium transition-colors ${available ? 'text-teal bg-teal-muted hover:bg-teal hover:text-white' : 'text-ink-faint bg-card border border-rule'}`}>
                {sp}
              </button>
            );
          })}
          {data.availableSpecialties.length === 0 && <span className="text-warning">(none available right now)</span>}
        </div>
      )}
      {data.estWaitMinutes != null && <div className="text-xs text-ink-muted">Estimated wait with the selected doctor: <span className="font-medium text-ink">~{data.estWaitMinutes} min</span></div>}
      {mismatch && <div className="text-xs text-warning bg-warning-bg rounded-lg px-2.5 py-1.5">The selected doctor ({selectedSpecialty}) differs from the suggested specialty. You can still continue.</div>}
      <div className="text-[10px] text-ink-faint">AI-assisted estimate to help order the queue — not a diagnosis. Clinicians decide.</div>
    </div>
  );
}
