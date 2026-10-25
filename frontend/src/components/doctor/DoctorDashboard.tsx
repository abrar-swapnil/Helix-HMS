import { useState } from 'react';
import { CheckCircle, Clock, Users, TrendingUp, Paperclip, Brain } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { AuthUser, Appointment, Doctor, DoctorStats, DoctorStatus } from '../../types';
import { api, errorMessage } from '../../lib/api';
import { useLiveQuery } from '../../lib/live';
import { useToast } from '../../lib/toast';
import { fmtDate, fmtTime, scoreLabel } from '../../lib/format';
import { Toast } from '../ui';
import RecordsModal from '../shared/RecordsModal';

const statusConfig: Record<DoctorStatus, { label: string; color: string; bg: string; ring: string }> = {
  available: { label: 'Available', color: 'text-success', bg: 'bg-success-bg', ring: 'ring-success/30' },
  busy: { label: 'Busy', color: 'text-warning', bg: 'bg-warning-bg', ring: 'ring-warning/30' },
  unavailable: { label: 'Not Available', color: 'text-danger', bg: 'bg-danger-bg', ring: 'ring-danger/30' },
};

interface Props {
  user: AuthUser;
  activeView: string;
}

export default function DoctorDashboard({ user, activeView }: Props) {
  // Live data: refreshes whenever reception books someone, a patient books/cancels, or the AI re-orders the queue.
  const meQ = useLiveQuery(() => api.get<Doctor>('/doctors/me'), ['doctors']);
  const queueQ = useLiveQuery(() => api.get<Appointment[]>('/appointments/queue/me'), ['appointments', 'documents'], { pollMs: 15000 });
  const statsQ = useLiveQuery(() => api.get<DoctorStats>('/stats/doctor'), ['appointments', 'stats']);
  const me = meQ.data;
  const waiting = queueQ.data ?? [];
  const stats = statsQ.data;
  const status: DoctorStatus = me?.status ?? 'available';
  const { toast, notify } = useToast();
  const [records, setRecords] = useState<{ id: string; name: string } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const weekTotal = stats?.thisWeek ?? 0;
  const seenToday = stats?.seenToday ?? 0;

  const changeStatus = async (s: DoctorStatus) => {
    if (!me || s === status) return;
    try {
      const r = await api.patch<{ doctor: Doctor; moved: number; stranded: number }>(`/doctors/${me.id}/status`, { status: s });
      if (s === 'unavailable' && r.moved > 0) notify(`You're now Not Available — ${r.moved} waiting patient${r.moved > 1 ? 's were' : ' was'} moved to other ${me.specialty} doctors.`, 'info');
      else if (s === 'unavailable' && r.stranded > 0) notify(`No other ${me.specialty} doctor is available — ${r.stranded} patient${r.stranded > 1 ? 's are' : ' is'} still waiting for you.`, 'warning');
      else notify(`Status set to ${statusConfig[s].label}`);
      await Promise.all([meQ.reload(), queueQ.reload()]);
    } catch (e) { notify(errorMessage(e), 'danger'); }
  };

  const markDone = async (id: string) => {
    setBusyId(id);
    try {
      await api.post(`/appointments/${id}/complete`);
      await Promise.all([queueQ.reload(), statsQ.reload(), meQ.reload()]);
    } catch (e) { notify(errorMessage(e), 'danger'); } finally { setBusyId(null); }
  };

  const cfg = statusConfig[status];
  void cfg;

  const recordsModal = records && <RecordsModal patientId={records.id} patientName={records.name} canUpload={false} onClose={() => setRecords(null)} />;

  if (activeView === 'waiting') {
    return (
      <div className="flex-1 overflow-y-auto">
        <PageHeader title="Waiting List" subtitle={`${waiting.length} patient${waiting.length !== 1 ? 's' : ''} waiting · ordered by AI priority (condition + waiting time)`} />
        <div className="px-8 py-6 space-y-3">
          {waiting.length === 0 && (
            <div className="bg-card rounded-2xl border border-rule p-12 text-center">
              <CheckCircle size={40} className="text-success mx-auto mb-3" />
              <p className="font-semibold text-ink" style={{ fontFamily: 'var(--font-display)' }}>All clear!</p>
              <p className="text-ink-muted text-sm mt-1">No patients in the waiting list</p>
            </div>
          )}
          {waiting.map((patient, idx) => {
            const sc = scoreLabel(patient.priorityScore ?? patient.healthScore ?? 0);
            return (
              <div key={patient.id} className={`bg-card rounded-2xl border p-5 flex items-center gap-4 ${patient.type === 'emergency' ? 'border-danger/40' : 'border-rule'}`}>
                <div className="w-8 h-8 bg-surface rounded-full flex items-center justify-center text-ink-muted font-semibold text-sm shrink-0" style={{ fontFamily: 'var(--font-display)' }}>
                  {idx + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-ink text-sm" style={{ fontFamily: 'var(--font-display)' }}>{patient.patientName}</span>
                    {patient.type === 'emergency' && (
                      <span className="text-xs font-medium px-2 py-0.5 rounded-full text-danger bg-danger-bg">EMERGENCY</span>
                    )}
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex items-center gap-1 ${sc.cls}`} title="AI priority score: condition + waiting time">
                      <Brain size={11} /> {Math.round(patient.priorityScore ?? 0)} · {sc.label}
                    </span>
                    {patient.reassignedFrom && <span className="text-xs text-info bg-info-bg px-2 py-0.5 rounded-full">Moved from {patient.reassignedFrom}</span>}
                  </div>
                  <div className="text-xs text-ink-muted mt-0.5">
                    {patient.patientAge != null ? `Age ${patient.patientAge} · ` : ''}Waiting since {fmtTime(patient.type === 'emergency' ? patient.arrivedAt ?? patient.time : patient.time)} · {patient.waitingMinutes ?? 0} min
                  </div>
                  {patient.symptoms && <div className="text-xs text-ink mt-1.5 line-clamp-2">“{patient.symptoms}”</div>}
                  {(patient.historyFlags?.length ?? 0) > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {patient.historyFlags!.map(h => <span key={h} className="text-[11px] font-medium text-teal bg-teal-muted px-2 py-0.5 rounded-full">{h}</span>)}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setRecords({ id: patient.patientId, name: patient.patientName })}
                  className="flex items-center gap-1.5 text-ink-muted hover:text-teal hover:bg-teal-muted text-xs font-medium px-3 py-2 rounded-xl transition-all"
                  style={{ fontFamily: 'var(--font-display)' }}
                  title="View the patient's uploaded medical records"
                >
                  <Paperclip size={14} /> Records
                </button>
                <button
                  onClick={() => markDone(patient.id)}
                  disabled={busyId === patient.id}
                  className="flex items-center gap-2 bg-success-bg hover:bg-success text-success hover:text-white disabled:opacity-60 text-xs font-medium px-3 py-2 rounded-xl transition-all"
                  style={{ fontFamily: 'var(--font-display)' }}
                >
                  <CheckCircle size={14} />
                  Done
                </button>
              </div>
            );
          })}
        </div>
        {recordsModal}
        <Toast {...toast} />
      </div>
    );
  }

  if (activeView === 'analytics') {
    return (
      <div className="flex-1 overflow-y-auto">
        <PageHeader title="My Analytics" subtitle="Your patient care statistics this week" />
        <div className="px-8 py-6 space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <StatCard label="Seen Today" value={seenToday} icon={<CheckCircle size={20} className="text-success" />} bg="bg-success-bg" />
            <StatCard label="Waiting Now" value={waiting.length} icon={<Clock size={20} className="text-warning" />} bg="bg-warning-bg" />
            <StatCard label="This Week" value={weekTotal} icon={<TrendingUp size={20} className="text-teal" />} bg="bg-teal-muted" />
          </div>

          <div className="bg-card rounded-2xl border border-rule p-6">
            <h3 className="font-semibold text-ink mb-5" style={{ fontFamily: 'var(--font-display)' }}>Patients Seen — This Week</h3>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={stats?.weekly ?? []}>
                <defs>
                  <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #E2E8F0', fontSize: 12 }} />
                <Area type="monotone" dataKey="patients" stroke="#10B981" strokeWidth={2.5} fill="url(#colorCount)" name="Patients" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-card rounded-2xl border border-rule p-6">
            <h3 className="font-semibold text-ink mb-4" style={{ fontFamily: 'var(--font-display)' }}>Recent Patients</h3>
            <div className="space-y-3">
              {(stats?.recent ?? []).length === 0 && <div className="text-sm text-ink-faint text-center py-4">No patients seen yet.</div>}
              {(stats?.recent ?? []).map((p, i) => (
                <div key={`${p.name}-${i}`} className="flex items-center gap-3 p-3 bg-surface rounded-xl">
                  <div className="w-8 h-8 bg-teal-muted rounded-full flex items-center justify-center text-teal font-semibold text-sm shrink-0" style={{ fontFamily: 'var(--font-display)' }}>
                    {p.name[0]}
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-ink">{p.name}</div>
                    <div className="text-xs text-ink-muted">{p.age != null ? `Age ${p.age} · ` : ''}Last visit {fmtDate(p.lastVisit)}</div>
                  </div>
                  <span className="text-xs text-success bg-success-bg px-2 py-1 rounded-full">Visited</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <Toast {...toast} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader title="My Dashboard" subtitle={`Welcome back, ${me?.name ?? user.name}`} />

      <div className="px-8 py-6 space-y-6">
        <div className="bg-card rounded-2xl border border-rule p-6">
          <h3 className="font-semibold text-ink mb-4" style={{ fontFamily: 'var(--font-display)' }}>Availability Status</h3>
          <div className="flex gap-3">
            {(Object.keys(statusConfig) as DoctorStatus[]).map(s => {
              const c = statusConfig[s];
              const isActive = status === s;
              return (
                <button
                  key={s}
                  onClick={() => changeStatus(s)}
                  className={`flex items-center gap-2 px-5 py-3 rounded-xl border-2 text-sm font-medium transition-all ${
                    isActive ? `${c.bg} ${c.color} border-current ring-2 ${c.ring}` : 'bg-surface text-ink-muted border-rule hover:border-ink-muted'
                  }`}
                  style={{ fontFamily: 'var(--font-display)' }}
                >
                  <span className={`w-2.5 h-2.5 rounded-full ${isActive ? (s === 'available' ? 'bg-success' : s === 'busy' ? 'bg-warning' : 'bg-danger') : 'bg-ink-faint'}`} />
                  {c.label}
                </button>
              );
            })}
          </div>
          {status === 'available' && (
            <p className="text-xs text-success mt-3 bg-success-bg rounded-lg px-3 py-2">
              ● You are visible to receptionists and patients. New appointments may be assigned.
            </p>
          )}
          {status === 'unavailable' && (
            <p className="text-xs text-danger mt-3 bg-danger-bg rounded-lg px-3 py-2">
              ● You are hidden from booking. Waiting patients are automatically moved to other {me?.specialty ?? ''} doctors.
            </p>
          )}
        </div>

        <div className="grid grid-cols-3 gap-4">
          <StatCard label="Seen Today" value={seenToday} icon={<CheckCircle size={20} className="text-success" />} bg="bg-success-bg" />
          <StatCard label="Waiting Now" value={waiting.length} icon={<Users size={20} className="text-warning" />} bg="bg-warning-bg" />
          <StatCard label="This Week" value={weekTotal} icon={<TrendingUp size={20} className="text-teal" />} bg="bg-teal-muted" />
        </div>

        <div className="bg-card rounded-2xl border border-rule p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-ink" style={{ fontFamily: 'var(--font-display)' }}>Next Up — Waiting List</h3>
            <span className="text-xs text-ink-muted bg-surface px-3 py-1 rounded-full">{waiting.length} patients</span>
          </div>
          {waiting.length === 0 && <div className="text-sm text-ink-faint text-center py-6">No patients are waiting right now.</div>}
          {waiting.slice(0, 3).map((patient, idx) => (
            <div key={patient.id} className={`flex items-center gap-4 py-3 ${idx < Math.min(waiting.length, 3) - 1 ? 'border-b border-rule' : ''}`}>
              <div className="w-7 h-7 bg-navy text-white rounded-full flex items-center justify-center text-xs font-bold shrink-0" style={{ fontFamily: 'var(--font-display)' }}>{idx + 1}</div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-ink">{patient.patientName}</span>
                  {patient.type === 'emergency' && <span className="text-xs text-danger bg-danger-bg px-1.5 py-0.5 rounded-full">EMRG</span>}
                  <span className={`text-xs px-1.5 py-0.5 rounded-full ${scoreLabel(patient.priorityScore ?? 0).cls}`}>{Math.round(patient.priorityScore ?? 0)}</span>
                </div>
                <span className="text-xs text-ink-muted">Waiting since {fmtTime(patient.type === 'emergency' ? patient.arrivedAt ?? patient.time : patient.time)} · {patient.waitingMinutes ?? 0} min</span>
              </div>
              <button onClick={() => markDone(patient.id)} disabled={busyId === patient.id} className="text-xs text-success bg-success-bg hover:bg-success hover:text-white disabled:opacity-60 px-3 py-1.5 rounded-lg transition-all font-medium" style={{ fontFamily: 'var(--font-display)' }}>Done</button>
            </div>
          ))}
          {waiting.length > 3 && (
            <p className="text-xs text-ink-muted text-center mt-3">+{waiting.length - 3} more in queue</p>
          )}
        </div>
      </div>
      <Toast {...toast} />
    </div>
  );
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="bg-card border-b border-rule px-8 py-5">
      <h1 className="text-xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{title}</h1>
      <p className="text-ink-muted text-sm mt-0.5">{subtitle}</p>
    </div>
  );
}

function StatCard({ label, value, icon, bg }: { label: string; value: number; icon: React.ReactNode; bg: string }) {
  return (
    <div className="bg-card rounded-2xl border border-rule p-5 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${bg} shrink-0`}>{icon}</div>
      <div>
        <div className="text-2xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{value}</div>
        <div className="text-xs text-ink-muted">{label}</div>
      </div>
    </div>
  );
}
