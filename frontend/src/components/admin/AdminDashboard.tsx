import { useState } from 'react';
import { Plus, Trash2, AlertTriangle, BedDouble, Users, CalendarCheck, Activity, X } from 'lucide-react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import type { Doctor, Room, AuthUser, AdminStats } from '../../types';
import ConfirmDialog from '../ConfirmDialog';
import { Modal, FormRow, Toast } from '../ui';
import { api, errorMessage } from '../../lib/api';
import { useLiveQuery } from '../../lib/live';
import { useToast } from '../../lib/toast';
import { SPECIALTIES } from '../../data/constants';
import { firstName, greeting } from '../../lib/format';

interface Props {
  user: AuthUser;
  activeView: string;
}

const statSpecialties = SPECIALTIES;

export default function AdminDashboard({ user, activeView }: Props) {
  // Everything below comes from the database and refreshes live whenever anyone (admin, reception, doctor, patient) changes it.
  const doctorsQ = useLiveQuery(() => api.get<Doctor[]>('/doctors'), ['doctors']);
  const roomsQ = useLiveQuery(() => api.get<Room[]>('/rooms'), ['rooms']);
  const statsQ = useLiveQuery(() => api.get<AdminStats>('/stats/admin'), ['stats', 'appointments', 'rooms', 'doctors']);
  const doctors = doctorsQ.data ?? [];
  const rooms = roomsQ.data ?? [];
  const stats = statsQ.data;
  const { toast, notify } = useToast();

  const [showAddDoctor, setShowAddDoctor] = useState(false);
  const [showAddRoom, setShowAddRoom] = useState(false);
  const [doctorForm, setDoctorForm] = useState({ name: '', email: '', phone: '', specialty: '' });
  const [roomForm, setRoomForm] = useState({ number: '', type: 'general' as Room['type'] });
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);

  // Confirm dialog state
  const [confirm, setConfirm] = useState<{ open: boolean; type: 'removeDoctor' | 'addDoctor' | 'removeRoom' | 'addRoom' | 'toggleRoom'; targetId?: string; targetName?: string }>({ open: false, type: 'removeDoctor' });
  const closeConfirm = () => setConfirm(c => ({ ...c, open: false }));

  const totalRooms = rooms.length;
  const availableRooms = rooms.filter(r => r.status === 'available').length;
  const totalDoctors = doctors.length;
  const availableDoctors = doctors.filter(d => d.status === 'available').length;
  const totalPatients = rooms.filter(r => r.patientId).length;
  const todayAppointments = stats?.todayAppointments ?? 0;
  const weekly = stats?.weekly ?? [];

  /** run an API call, refresh the lists, and show success / error */
  const run = async (fn: () => Promise<string | void>, onFail?: (msg: string) => void) => {
    setBusy(true);
    try {
      const msg = await fn();
      if (msg) notify(msg);
      await Promise.all([doctorsQ.reload(), roomsQ.reload(), statsQ.reload()]);
      return true;
    } catch (e) {
      if (onFail) onFail(errorMessage(e)); else notify(errorMessage(e), 'danger');
      return false;
    } finally { setBusy(false); closeConfirm(); }
  };

  const addDoctor = () => {
    if (!doctorForm.name.trim() || !doctorForm.email.trim()) { setFormError('Name and email are required.'); return; }
    setFormError('');
    setConfirm({ open: true, type: 'addDoctor', targetName: doctorForm.name });
  };

  const confirmAddDoctor = () => run(async () => {
    const d = await api.post<Doctor>('/doctors', { ...doctorForm, specialty: doctorForm.specialty || 'General Medicine' });
    setDoctorForm({ name: '', email: '', phone: '', specialty: '' });
    setShowAddDoctor(false);
    return `${d.name} added to the roster`;
  }, setFormError);

  const removeDoctor = (id: string) => {
    const doc = doctors.find(d => d.id === id);
    setConfirm({ open: true, type: 'removeDoctor', targetId: id, targetName: doc?.name });
  };

  const confirmRemoveDoctor = () => run(async () => {
    const r = await api.del<{ moved: number; cancelled: number }>(`/doctors/${confirm.targetId}`);
    return `${confirm.targetName} removed` + (r.moved ? ` · ${r.moved} appointment(s) moved to another doctor` : '') + (r.cancelled ? ` · ${r.cancelled} cancelled (no replacement)` : '');
  });

  const toggleDept = (id: string) => {
    const d = doctors.find(x => x.id === id);
    if (!d) return;
    void run(async () => { await api.patch(`/doctors/${id}/department`, { department: d.department === 'general' ? 'emergency' : 'general' }); });
  };

  const addRoom = () => {
    if (!roomForm.number.trim()) { setFormError('Room number is required.'); return; }
    setFormError('');
    setConfirm({ open: true, type: 'addRoom', targetName: `Room ${roomForm.number}` });
  };

  const confirmAddRoom = () => run(async () => {
    await api.post('/rooms', { number: roomForm.number, type: roomForm.type });
    setRoomForm({ number: '', type: 'general' });
    setShowAddRoom(false);
    return `Room ${roomForm.number.toUpperCase()} added`;
  }, setFormError);

  const removeRoom = (id: string) => {
    const room = rooms.find(r => r.id === id);
    setConfirm({ open: true, type: 'removeRoom', targetId: id, targetName: `Room ${room?.number}` });
  };

  const confirmRemoveRoom = () => run(async () => { await api.del(`/rooms/${confirm.targetId}`); return `${confirm.targetName} removed`; });

  const toggleRoomType = (id: string) => {
    const room = rooms.find(r => r.id === id);
    setConfirm({ open: true, type: 'toggleRoom', targetId: id, targetName: `Room ${room?.number}` });
  };

  const confirmToggleRoom = () => {
    const room = rooms.find(r => r.id === confirm.targetId);
    if (!room) { closeConfirm(); return; }
    void run(async () => { await api.patch(`/rooms/${room.id}/type`, { type: room.type === 'general' ? 'emergency' : 'general' }); });
  };

  const handleConfirm = () => {
    if (busy) return;
    if (confirm.type === 'removeDoctor') confirmRemoveDoctor();
    else if (confirm.type === 'addDoctor') confirmAddDoctor();
    else if (confirm.type === 'removeRoom') confirmRemoveRoom();
    else if (confirm.type === 'addRoom') confirmAddRoom();
    else if (confirm.type === 'toggleRoom') confirmToggleRoom();
  };

  const dialogProps = {
    removeDoctor: { variant: 'danger' as const, title: 'Remove Doctor', message: `Are you sure you want to remove ${confirm.targetName} from the system? Their login stops working and their scheduled appointments are moved to another doctor of the same specialty (or cancelled if there is none).`, confirmLabel: 'Yes, Remove' },
    addDoctor: { variant: 'info' as const, title: 'Add Doctor', message: `Add ${confirm.targetName} to the hospital roster? They will immediately be visible to receptionists and patients.`, confirmLabel: 'Yes, Add Doctor' },
    removeRoom: { variant: 'danger' as const, title: 'Remove Room', message: `Remove ${confirm.targetName} from the system? If the room is currently occupied, the patient record will not be affected but the room will be unlinked.`, confirmLabel: 'Yes, Remove Room' },
    addRoom: { variant: 'info' as const, title: 'Add Room', message: `Add ${confirm.targetName} (${roomForm.type.toUpperCase()}) to the hospital? It will be immediately available for booking.`, confirmLabel: 'Yes, Add Room' },
    toggleRoom: { variant: 'warning' as const, title: 'Change Room Type', message: `Change ${confirm.targetName} between General and Emergency designation? This may affect current patient assignments and room priority queuing.`, confirmLabel: 'Yes, Change Type' },
  };

  const currentDialog = dialogProps[confirm.type];

  const content = (() => {
  if (activeView === 'rooms') return <RoomsView rooms={rooms} error={formError} busy={busy} onAdd={() => { setFormError(''); setShowAddRoom(true); }} onRemove={removeRoom} onToggleType={toggleRoomType} showModal={showAddRoom} setShowModal={setShowAddRoom} form={roomForm} setForm={setRoomForm} onSave={addRoom} confirm={confirm} onConfirm={handleConfirm} onCancelConfirm={closeConfirm} />;
  if (activeView === 'doctors') return <DoctorsView doctors={doctors} error={formError} busy={busy} onToggleDept={toggleDept} onAdd={() => { setFormError(''); setShowAddDoctor(true); }} onRemove={removeDoctor} showModal={showAddDoctor} setShowModal={setShowAddDoctor} form={doctorForm} setForm={setDoctorForm} onSave={addDoctor} confirm={confirm} onConfirm={handleConfirm} onCancelConfirm={closeConfirm} />;
  if (activeView === 'statistics') return <StatisticsView doctors={doctors} weekly={weekly} />;

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader title="Admin Overview" subtitle={`${greeting()}, ${firstName(user.name)}. Here's today's summary.`} />

      <div className="px-8 py-6 space-y-6">
        <div className="grid grid-cols-4 gap-4">
          <StatCard label="Total Rooms" value={totalRooms} sub={`${availableRooms} available`} color="bg-info-bg" icon={<BedDouble size={20} className="text-info" />} />
          <StatCard label="Total Doctors" value={totalDoctors} sub={`${availableDoctors} on duty`} color="bg-success-bg" icon={<Users size={20} className="text-success" />} />
          <StatCard label="Inpatients" value={totalPatients} sub="currently admitted" color="bg-warning-bg" icon={<Activity size={20} className="text-warning" />} />
          <StatCard label="Today's Appts." value={todayAppointments} sub="scheduled" color="bg-teal-muted" icon={<CalendarCheck size={20} className="text-teal" />} />
        </div>

        <div className="grid grid-cols-5 gap-4">
          <div className="col-span-3 bg-card rounded-2xl border border-rule p-6">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="font-semibold text-ink" style={{ fontFamily: 'var(--font-display)' }}>Weekly Patient Flow</h3>
                <p className="text-ink-faint text-xs mt-0.5">Patients & appointments this week</p>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={weekly}>
                <defs>
                  <linearGradient id="colorPatients" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06A4A8" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#06A4A8" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorAppts" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0D2B45" stopOpacity={0.1} />
                    <stop offset="95%" stopColor="#0D2B45" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #E2E8F0', fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="patients" stroke="#06A4A8" strokeWidth={2} fill="url(#colorPatients)" name="Patients" />
                <Area type="monotone" dataKey="appointments" stroke="#0D2B45" strokeWidth={2} fill="url(#colorAppts)" name="Appointments" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="col-span-2 bg-card rounded-2xl border border-rule p-6">
            <h3 className="font-semibold text-ink mb-4" style={{ fontFamily: 'var(--font-display)' }}>Room Status</h3>
            <div className="space-y-2">
              {[
                { type: 'General', count: rooms.filter(r => r.type === 'general').length, occ: rooms.filter(r => r.type === 'general' && r.status === 'occupied').length, color: '#3B82F6' },
                { type: 'Emergency', count: rooms.filter(r => r.type === 'emergency').length, occ: rooms.filter(r => r.type === 'emergency' && r.status === 'occupied').length, color: '#EF4444' },
                { type: 'OT', count: rooms.filter(r => r.type === 'ot').length, occ: rooms.filter(r => r.type === 'ot' && r.status === 'occupied').length, color: '#F59E0B' },
                { type: 'ICU', count: rooms.filter(r => r.type === 'icu').length, occ: rooms.filter(r => r.type === 'icu' && r.status === 'occupied').length, color: '#8B5CF6' },
              ].map(item => (
                <div key={item.type} className="flex items-center gap-3">
                  <div className="w-20 text-xs text-ink-muted">{item.type}</div>
                  <div className="flex-1 bg-surface rounded-full h-2 overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${item.count ? (item.occ / item.count) * 100 : 0}%`, backgroundColor: item.color }} />
                  </div>
                  <div className="text-xs text-ink-muted w-12 text-right">{item.occ}/{item.count}</div>
                </div>
              ))}
            </div>

            <h3 className="font-semibold text-ink mt-6 mb-3" style={{ fontFamily: 'var(--font-display)' }}>Doctor Status</h3>
            <div className="space-y-2">
              {doctors.length === 0 && <div className="text-xs text-ink-faint">No doctors yet. Add the first one in the Doctors tab.</div>}
              {doctors.slice(0, 4).map(doc => (
                <div key={doc.id} className="flex items-center gap-2">
                  <StatusDot status={doc.status} />
                  <span className="text-xs text-ink flex-1 truncate">{doc.name}</span>
                  <span className="text-xs text-ink-faint">{doc.specialty.slice(0, 6)}…</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
  })();
  return (<>{content}<Toast {...toast} /></>);
}

function RoomsView({ rooms, error, busy, onAdd, onRemove, onToggleType, showModal, setShowModal, form, setForm, onSave, confirm, onConfirm, onCancelConfirm }: {
  error: string; busy: boolean; rooms: Room[]; onAdd: () => void; onRemove: (id: string) => void; onToggleType: (id: string) => void;
  showModal: boolean; setShowModal: (v: boolean) => void; form: { number: string; type: Room['type'] }; setForm: (f: any) => void; onSave: () => void;
  confirm: { open: boolean; type: string; targetName?: string }; onConfirm: () => void; onCancelConfirm: () => void;
}) {
  const typeColors: Record<string, string> = { general: 'text-info bg-info-bg', emergency: 'text-danger bg-danger-bg', ot: 'text-warning bg-warning-bg', icu: 'text-purple-600 bg-purple-50' };

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader title="Room Management" subtitle="Monitor and manage all hospital rooms">
        <button onClick={onAdd} className="flex items-center gap-2 bg-teal hover:bg-teal-light text-white text-sm font-medium px-4 py-2 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
          <Plus size={16} /> Add Room
        </button>
      </PageHeader>

      <div className="px-8 py-6">
        {rooms.length === 0 && (
          <div className="bg-card rounded-2xl border border-rule p-10 text-center text-sm text-ink-faint">No rooms yet. Use “Add Room” to create the first one.</div>
        )}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {rooms.map(room => (
            <div key={room.id} className={`bg-card rounded-2xl border p-4 ${room.status === 'occupied' ? 'border-warning' : 'border-rule'}`}>
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="font-bold text-xl text-ink" style={{ fontFamily: 'var(--font-display)' }}>{room.number}</div>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${typeColors[room.type]}`}>{room.type.toUpperCase()}</span>
                </div>
                <div className="flex gap-1">
                  {(room.type === 'general' || room.type === 'emergency') && (
                    <button onClick={() => onToggleType(room.id)} title="Toggle General/Emergency" className="p-1.5 rounded-lg hover:bg-warning-bg transition-colors">
                      <AlertTriangle size={13} className="text-warning" />
                    </button>
                  )}
                  <button onClick={() => onRemove(room.id)} className="p-1.5 rounded-lg hover:bg-danger-bg transition-colors">
                    <Trash2 size={13} className="text-danger" />
                  </button>
                </div>
              </div>
              <div className={`text-xs font-medium ${room.status === 'available' ? 'text-success' : 'text-warning'}`}>
                {room.status === 'available' ? '● Available' : '● Occupied'}
              </div>
              {room.patientName && <div className="text-xs text-ink-muted mt-1 truncate">{room.patientName}</div>}
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <Modal title="Add Room" onClose={() => setShowModal(false)} onSave={onSave} error={error} busy={busy}>
          <FormRow label="Room Number" value={form.number} onChange={v => setForm((f: any) => ({ ...f, number: v }))} placeholder="e.g. 201" />
          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Room Type</label>
            <select value={form.type} onChange={e => setForm((f: any) => ({ ...f, type: e.target.value }))} className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-sm text-ink focus:border-teal transition-colors">
              <option value="general">General</option>
              <option value="emergency">Emergency</option>
              <option value="ot">OT (Operating Theatre)</option>
              <option value="icu">ICU</option>
            </select>
          </div>
        </Modal>
      )}
      <ConfirmDialog
        open={confirm.open && (confirm.type === 'addRoom' || confirm.type === 'removeRoom' || confirm.type === 'toggleRoom')}
        variant={confirm.type === 'removeRoom' ? 'danger' : confirm.type === 'toggleRoom' ? 'warning' : 'info'}
        title={confirm.type === 'removeRoom' ? 'Remove Room' : confirm.type === 'toggleRoom' ? 'Change Room Type' : 'Add Room'}
        message={
          confirm.type === 'removeRoom'
            ? `Are you sure you want to remove ${confirm.targetName}? If the room is currently occupied, the patient record will be unlinked.`
            : confirm.type === 'toggleRoom'
            ? `Change ${confirm.targetName} between General and Emergency designation? This affects room priority and queue ordering.`
            : `Add ${confirm.targetName} to the hospital? It will be immediately available for booking.`
        }
        confirmLabel={confirm.type === 'removeRoom' ? 'Yes, Remove' : confirm.type === 'toggleRoom' ? 'Yes, Change Type' : 'Yes, Add Room'}
        onConfirm={onConfirm}
        onCancel={onCancelConfirm}
      />
    </div>
  );
}

function DoctorsView({ doctors, error, busy, onToggleDept, onAdd, onRemove, showModal, setShowModal, form, setForm, onSave, confirm, onConfirm, onCancelConfirm }: {
  doctors: Doctor[]; error: string; busy: boolean; onToggleDept: (id: string) => void;
  onAdd: () => void; onRemove: (id: string) => void;
  showModal: boolean; setShowModal: (v: boolean) => void;
  form: { name: string; email: string; phone: string; specialty: string }; setForm: (f: any) => void; onSave: () => void;
  confirm: { open: boolean; type: string; targetName?: string }; onConfirm: () => void; onCancelConfirm: () => void;
}) {
  const emergencyDocs = doctors.filter(d => d.department === 'emergency');
  const generalDocs = doctors.filter(d => d.department === 'general');

  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader title="Doctor Management" subtitle="Manage physicians and assign them to departments">
        <button onClick={onAdd} className="flex items-center gap-2 bg-teal hover:bg-teal-light text-white text-sm font-medium px-4 py-2 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
          <Plus size={16} /> Add Doctor
        </button>
      </PageHeader>

      <div className="px-8 py-6 space-y-6">
        {/* Department summary */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-card rounded-2xl border border-rule p-5 flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-info-bg flex items-center justify-center shrink-0">
              <Users size={18} className="text-info" />
            </div>
            <div>
              <div className="text-2xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{generalDocs.length}</div>
              <div className="text-xs text-ink-muted">General Department</div>
            </div>
          </div>
          <div className="bg-card rounded-2xl border border-danger/30 p-5 flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl bg-danger-bg flex items-center justify-center shrink-0">
              <AlertTriangle size={18} className="text-danger" />
            </div>
            <div>
              <div className="text-2xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{emergencyDocs.length}</div>
              <div className="text-xs text-ink-muted">Emergency Department</div>
            </div>
          </div>
        </div>

        {/* Doctor table */}
        <div className="bg-card rounded-2xl border border-rule overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-rule bg-surface">
                {['Name', 'Specialty', 'Department', 'Status', 'Today', 'Change Dept.', ''].map(h => (
                  <th key={h} className="text-left text-xs font-semibold text-ink-muted uppercase tracking-wide px-5 py-3.5">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {doctors.length === 0 && (
                <tr><td colSpan={7} className="px-5 py-10 text-center text-sm text-ink-faint">No doctors yet. Use “Add Doctor”, or ask doctors to register with the staff access code.</td></tr>
              )}
              {doctors.map(doc => (
                <tr key={doc.id} className="border-b border-rule last:border-0 hover:bg-surface/50 transition-colors">
                  <td className="px-5 py-3.5">
                    <div className="font-medium text-ink text-sm">{doc.name}</div>
                    <div className="text-xs text-ink-faint">{doc.email}</div>
                  </td>
                  <td className="px-5 py-3.5 text-sm text-ink-muted">{doc.specialty}</td>
                  <td className="px-5 py-3.5">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${doc.department === 'emergency' ? 'text-danger bg-danger-bg' : 'text-info bg-info-bg'}`}>
                      {doc.department === 'emergency' ? '🚨 Emergency' : '📋 General'}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <StatusBadge status={doc.status} />
                  </td>
                  <td className="px-5 py-3.5 text-sm text-ink-muted">{doc.patientsToday} pts</td>
                  <td className="px-5 py-3.5">
                    <button
                      onClick={() => onToggleDept(doc.id)}
                      title={`Move to ${doc.department === 'emergency' ? 'General' : 'Emergency'} dept.`}
                      className={`text-xs font-medium px-3 py-1.5 rounded-lg border transition-all ${
                        doc.department === 'emergency'
                          ? 'text-info border-info/30 hover:bg-info-bg'
                          : 'text-danger border-danger/30 hover:bg-danger-bg'
                      }`}
                      style={{ fontFamily: 'var(--font-display)' }}
                    >
                      → {doc.department === 'emergency' ? 'General' : 'Emergency'}
                    </button>
                  </td>
                  <td className="px-5 py-3.5">
                    <button onClick={() => onRemove(doc.id)} className="p-1.5 rounded-lg hover:bg-danger-bg transition-colors">
                      <Trash2 size={14} className="text-danger" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showModal && (
        <Modal title="Add Doctor" onClose={() => setShowModal(false)} onSave={onSave} error={error} busy={busy}>
          <FormRow label="Full Name" value={form.name} onChange={v => setForm((f: any) => ({ ...f, name: v }))} placeholder="Dr. Jane Smith" />
          <FormRow label="Email" value={form.email} onChange={v => setForm((f: any) => ({ ...f, email: v }))} placeholder="doctor@hospital.com" type="email" />
          <FormRow label="Phone" value={form.phone} onChange={v => setForm((f: any) => ({ ...f, phone: v }))} placeholder="+1 (555) 000-0000" />
          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Specialty</label>
            <select value={form.specialty} onChange={e => setForm((f: any) => ({ ...f, specialty: e.target.value }))} className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-sm text-ink focus:border-teal transition-colors">
              <option value="">Select specialty</option>
              {statSpecialties.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="flex items-start gap-2 bg-info-bg rounded-xl px-3 py-2.5">
            <AlertTriangle size={14} className="text-info mt-0.5 shrink-0" />
            <p className="text-xs text-ink-muted">New doctors are added to the <strong className="text-ink">General</strong> department by default. You can reassign them to Emergency using the table toggle after saving. The doctor then registers with this same email to get a login.</p>
          </div>
        </Modal>
      )}
      <ConfirmDialog
        open={confirm.open && (confirm.type === 'addDoctor' || confirm.type === 'removeDoctor')}
        variant={confirm.type === 'removeDoctor' ? 'danger' : 'info'}
        title={confirm.type === 'removeDoctor' ? 'Remove Doctor' : 'Add Doctor'}
        message={
          confirm.type === 'removeDoctor'
            ? `Are you sure you want to remove ${confirm.targetName} from the system? Their login stops working and their scheduled appointments are moved to another doctor of the same specialty (or cancelled if there is none).`
            : `Add ${confirm.targetName} to the hospital roster? They will be immediately visible to receptionists and patients.`
        }
        confirmLabel={confirm.type === 'removeDoctor' ? 'Yes, Remove' : 'Yes, Add Doctor'}
        onConfirm={onConfirm}
        onCancel={onCancelConfirm}
      />
    </div>
  );
}

function StatisticsView({ doctors, weekly }: { doctors: Doctor[]; weekly: { day: string; patients: number; appointments: number }[] }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <PageHeader title="Statistics" subtitle="Hospital performance metrics and analytics" />
      <div className="px-8 py-6 space-y-6">
        <div className="bg-card rounded-2xl border border-rule p-6">
          <h3 className="font-semibold text-ink mb-5" style={{ fontFamily: 'var(--font-display)' }}>Weekly Patient Volume</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={weekly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#94A3B8' }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #E2E8F0', fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="patients" fill="#06A4A8" radius={[4, 4, 0, 0]} name="Patients" />
              <Bar dataKey="appointments" fill="#0D2B45" radius={[4, 4, 0, 0]} name="Appointments" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-card rounded-2xl border border-rule p-6">
          <h3 className="font-semibold text-ink mb-5" style={{ fontFamily: 'var(--font-display)' }}>Doctors by Specialty</h3>
          <div className="grid grid-cols-4 gap-3">
            {statSpecialties.map(s => {
              const count = doctors.filter(d => d.specialty === s).length;
              return (
                <div key={s} className="bg-surface rounded-xl p-3 text-center">
                  <div className="text-2xl font-bold text-navy" style={{ fontFamily: 'var(--font-display)' }}>{count}</div>
                  <div className="text-xs text-ink-muted mt-1">{s}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function PageHeader({ title, subtitle, children }: { title: string; subtitle: string; children?: React.ReactNode }) {
  return (
    <div className="bg-card border-b border-rule px-8 py-5 flex items-center justify-between">
      <div>
        <h1 className="text-xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{title}</h1>
        <p className="text-ink-muted text-sm mt-0.5">{subtitle}</p>
      </div>
      {children && <div>{children}</div>}
    </div>
  );
}

function StatCard({ label, value, sub, color, icon }: { label: string; value: number; sub: string; color: string; icon: React.ReactNode }) {
  return (
    <div className="bg-card rounded-2xl border border-rule p-5 flex items-start gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${color} shrink-0`}>{icon}</div>
      <div>
        <div className="text-2xl font-bold text-ink" style={{ fontFamily: 'var(--font-display)' }}>{value}</div>
        <div className="text-xs font-medium text-ink-muted">{label}</div>
        <div className="text-xs text-ink-faint mt-0.5">{sub}</div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    available: 'text-success bg-success-bg',
    busy: 'text-warning bg-warning-bg',
    unavailable: 'text-danger bg-danger-bg',
  };
  return <span className={`text-xs font-medium px-2.5 py-1 rounded-full capitalize ${map[status] || ''}`}>{status}</span>;
}

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = { available: 'bg-success', busy: 'bg-warning', unavailable: 'bg-danger' };
  return <span className={`w-2 h-2 rounded-full shrink-0 ${map[status] || 'bg-ink-faint'}`} />;
}
