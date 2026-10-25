import { useState, useRef, useEffect } from 'react';
import {
  Shield, UserRound, Stethoscope, ClipboardList, ArrowLeft,
  Eye, EyeOff, Phone, Mail,
  Bot, Send, X, Ambulance, Heart, HelpCircle,
  Activity, Users, BedDouble, Globe, ChevronRight,
} from 'lucide-react';
import type { Role, AuthUser, Meta } from '../types';
import { api, errorMessage, streamChat } from '../lib/api';
import { SPECIALTIES as SPECIALTY_LIST } from '../data/constants';

interface Props {
  onLogin: (user: AuthUser) => void;
}

type Step = 'landing' | 'select' | 'login' | 'register' | 'otp' | 'profile';

const SPECIALTIES = SPECIALTY_LIST;

const roles = [
  { id: 'admin' as Role, label: 'Administrator', desc: 'Hospital admin & system management', icon: Shield, color: '#3B82F6', bg: '#EEF4FF' },
  { id: 'receptionist' as Role, label: 'Receptionist', desc: 'Patient & room management', icon: ClipboardList, color: '#06A4A8', bg: '#E0F5F5' },
  { id: 'doctor' as Role, label: 'Doctor', desc: 'Patient care & appointments', icon: Stethoscope, color: '#10B981', bg: '#D1FAE5' },
  { id: 'patient' as Role, label: 'Patient', desc: 'Book appointments & view records', icon: UserRound, color: '#F59E0B', bg: '#FEF3C7' },
];

interface ChatMsg { id: string; from: 'user' | 'bot'; text: string; }

interface AuthResult {
  otpRequired?: boolean;
  challengeId?: string;
  devCode?: string | null;
  phone?: string;
  user?: AuthUser;
}

const DEFAULT_HOSPITAL = { name: 'Helix HMS', phone: '+1 (800) 4-HELIX', ambulance: '+1 (800) HLX-AMBU', email: 'support@helixhms.com', website: 'helixhms.com', emergency: '911' };

/** Tiny markdown: **bold** only (the AI uses it for emphasis). Everything else is rendered as plain text (no HTML injection). */
function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
}

export default function Login({ onLogin }: Props) {
  const [step, setStep] = useState<Step>('landing');
  const [selectedRole, setSelectedRole] = useState<Role | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<ChatMsg[]>([
    { id: 'm0', from: 'bot', text: '👋 Hi! I\'m Helix AI. I can help with ambulance dispatch, health guidance, finding doctors and portal navigation. How can I help?' },
  ]);
  const [chatInput, setChatInput] = useState('');
  const [botTyping, setBotTyping] = useState(false);
  const [chatMode, setChatMode] = useState<'ollama' | 'basic'>('basic');
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [form, setForm] = useState({
    username: '', password: '', phone: '', email: '',
    fullName: '', specialty: '', gender: 'male', age: '', address: '', staffCode: '',
  });

  // live (non-secret) info from the server: contact details, real counts, whether a staff code is needed
  const [meta, setMeta] = useState<Meta | null>(null);
  const [pubStats, setPubStats] = useState({ departments: 0, doctors: 0, beds: 0, patientsServed: 0 });
  const [staffCodeRequired, setStaffCodeRequired] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [challenge, setChallenge] = useState<{ id: string; devCode?: string | null; phone?: string } | null>(null);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const hospital = meta?.hospital ?? DEFAULT_HOSPITAL;

  useEffect(() => {
    api.get<Meta>('/meta').then(setMeta).catch(() => {});
    api.get<typeof pubStats>('/public/stats').then(setPubStats).catch(() => {});
    api.get<{ staffCodeRequired: boolean }>('/auth/config').then(c => setStaffCodeRequired(c.staffCodeRequired)).catch(() => {});
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMsgs, botTyping]);

  useEffect(() => {
    if (chatOpen) api.get<{ mode: 'ollama' | 'basic' }>('/chat/status').then(r => setChatMode(r.mode)).catch(() => {});
  }, [chatOpen]);

  const setField = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const goStep = (s: Step) => { setError(''); setStep(s); };

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text || botTyping) return;
    const userMsg: ChatMsg = { id: `u${Date.now()}`, from: 'user', text };
    const botId = `b${Date.now()}`;
    const history = [...chatMsgs, userMsg].filter(m => m.id !== 'm0').slice(-10)
      .map(m => ({ role: m.from === 'user' ? ('user' as const) : ('assistant' as const), content: m.text }));
    setChatMsgs(prev => [...prev, userMsg]);
    setChatInput('');
    setBotTyping(true);
    let started = false;
    try {
      await streamChat(history, setChatMode, delta => {
        if (!started) {
          started = true;
          setBotTyping(false);
          setChatMsgs(prev => [...prev, { id: botId, from: 'bot', text: delta }]);
        } else {
          setChatMsgs(prev => prev.map(m => (m.id === botId ? { ...m, text: m.text + delta } : m)));
        }
      });
    } catch (e) {
      setChatMsgs(prev => started
        ? prev.map(m => (m.id === botId ? { ...m, text: m.text + '\n\n(' + errorMessage(e) + ')' } : m))
        : [...prev, { id: botId, from: 'bot', text: '⚠️ ' + errorMessage(e) }]);
    } finally {
      setBotTyping(false);
    }
  };

  const handleOtpChange = (i: number, val: string) => {
    const digits = val.replace(/\D/g, '');
    if (digits.length > 1) {                       // pasted a whole code
      const next = ['', '', '', '', '', ''];
      digits.slice(0, 6).split('').forEach((d, k) => { next[k] = d; });
      setOtp(next);
      (document.getElementById(`otp-${Math.min(digits.length, 5)}`) as HTMLInputElement)?.focus();
      return;
    }
    const next = [...otp];
    next[i] = digits;
    setOtp(next);
    if (digits && i < 5) (document.getElementById(`otp-${i + 1}`) as HTMLInputElement)?.focus();
  };

  const afterAuth = (r: AuthResult) => {
    if (r.otpRequired && r.challengeId) {
      setChallenge({ id: r.challengeId, devCode: r.devCode, phone: r.phone });
      setOtp(['', '', '', '', '', '']);
      setError('');
      setStep('otp');
    } else if (r.user) {
      onLogin(r.user);
    }
  };

  const submitLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(''); setBusy(true); setAuthMode('login');
    try {
      afterAuth(await api.post<AuthResult>('/auth/login', {
        role: selectedRole, username: form.username, password: form.password, phone: form.phone, specialty: form.specialty,
      }));
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const submitRegister = async () => {
    setError(''); setBusy(true); setAuthMode('register');
    try {
      afterAuth(await api.post<AuthResult>('/auth/register', {
        role: selectedRole, username: form.username, password: form.password, phone: form.phone, email: form.email,
        fullName: form.fullName, specialty: form.specialty, staffCode: form.staffCode,
      }));
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const handleLogin = (e: React.FormEvent) => { void submitLogin(e); };

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedRole === 'doctor') { goStep('profile'); return; }     // doctors confirm their profile first
    void submitRegister();
  };

  const verifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!challenge) return;
    setError(''); setBusy(true);
    try {
      const r = await api.post<AuthResult>('/auth/verify-otp', { challengeId: challenge.id, code: otp.join('') });
      if (r.user) onLogin(r.user);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const resendOtp = async () => {
    if (!challenge) return;
    setError('');
    try {
      const r = await api.post<{ challengeId: string; devCode?: string | null }>('/auth/resend-otp', { challengeId: challenge.id });
      setChallenge({ ...challenge, id: r.challengeId, devCode: r.devCode });
      setOtp(['', '', '', '', '', '']);
    } catch (err) { setError(errorMessage(err)); }
  };

  const roleInfo = roles.find(r => r.id === selectedRole);

  // OTP step
  if (step === 'otp') {
    return (
      <AuthShell onBack={() => goStep(authMode)} role={roleInfo}>
        <h2 className="text-2xl font-bold text-navy mb-1" style={{ fontFamily: 'var(--font-display)' }}>Verify Identity</h2>
        <p className="text-ink-muted text-sm mb-8">
          Enter the 6-digit OTP sent to {challenge?.phone || form.phone || 'your phone'}
        </p>
        <form onSubmit={verifyOtp} className="space-y-6">
          <div className="flex gap-2 justify-between">
            {otp.map((val, i) => (
              <input key={i} id={`otp-${i}`} type="text" inputMode="numeric" maxLength={6} value={val}
                onChange={e => handleOtpChange(i, e.target.value)}
                onKeyDown={e => { if (e.key === 'Backspace' && !otp[i] && i > 0) (document.getElementById(`otp-${i - 1}`) as HTMLInputElement)?.focus(); }}
                className="w-12 h-14 text-center text-xl font-bold bg-surface border-2 border-rule rounded-xl text-ink focus:border-teal transition-colors"
              />
            ))}
          </div>
          {error && <div className="text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
          <p className="text-ink-faint text-xs text-center">
            {challenge?.devCode && (
              <>Demo mode: your code is <span className="font-mono font-semibold text-ink">{challenge.devCode}</span> ·{' '}
                <button type="button" className="text-teal hover:underline" onClick={() => setOtp(challenge.devCode!.split(''))}>Auto-fill</button> ·{' '}</>
            )}
            <button type="button" className="text-teal hover:underline" onClick={resendOtp}>Resend code</button>
          </p>
          <button type="submit" disabled={busy || otp.join('').length < 6} className="w-full bg-teal hover:bg-teal-light disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
            {busy ? 'Verifying…' : 'Verify & Continue'}
          </button>
        </form>
      </AuthShell>
    );
  }

  // Doctor profile completion
  if (step === 'profile' && selectedRole === 'doctor') {
    return (
      <AuthShell onBack={() => goStep('register')} role={roleInfo}>
        <h2 className="text-2xl font-bold text-navy mb-1" style={{ fontFamily: 'var(--font-display)' }}>Doctor Profile</h2>
        <p className="text-ink-muted text-sm mb-6">Complete your professional details</p>
        <form onSubmit={(e) => { e.preventDefault(); void submitRegister(); }} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Full Name</label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-teal font-semibold text-sm">Dr.</span>
              <input
                type="text" value={form.fullName} onChange={e => setField('fullName', e.target.value)}
                placeholder="Your full name" required
                className="w-full bg-surface border border-rule rounded-xl pl-12 pr-4 py-3 text-ink text-sm placeholder:text-ink-faint focus:border-teal transition-colors"
              />
            </div>
          </div>
          <FormField label="Email" type="email" value={form.email} onChange={v => setField('email', v)} placeholder="doctor@hospital.com" required />
          <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Specialty</label>
            <select value={form.specialty} onChange={e => setField('specialty', e.target.value)} required
              className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm focus:border-teal transition-colors">
              <option value="">Select specialty</option>
              {SPECIALTIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Create a password" required
            suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
          />
          {staffCodeRequired && (
            <FormField label="Staff Access Code" type="password" value={form.staffCode} onChange={v => setField('staffCode', v)} placeholder="Given to you by the hospital administrator" required />
          )}
          {error && <div className="text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
          <button type="submit" disabled={busy} className="w-full bg-teal hover:bg-teal-light disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
            {busy ? 'Please wait…' : 'Complete Registration'}
          </button>
        </form>
      </AuthShell>
    );
  }

  // Role selection
  if (step === 'select') {
    return (
      <div className="min-h-full bg-surface flex flex-col">
        <HelixHeader />
        <div className="flex-1 flex flex-col items-center justify-center px-4 py-12">
          <div className="max-w-2xl w-full">
            <button onClick={() => goStep('landing')} className="flex items-center gap-1.5 text-ink-muted hover:text-ink text-sm mb-8 transition-colors">
              <ArrowLeft size={14} /> Back to home
            </button>
            <h2 className="text-3xl font-bold text-navy mb-2" style={{ fontFamily: 'var(--font-display)' }}>Access Portal</h2>
            <p className="text-ink-muted mb-8">Select your role to sign in or register</p>
            <div className="grid grid-cols-2 gap-4">
              {roles.map(role => {
                const Icon = role.icon;
                return (
                  <button key={role.id} onClick={() => { setSelectedRole(role.id); setError(''); setStep('login'); }}
                    className="group bg-card rounded-2xl p-6 border border-rule text-left hover:border-teal hover:shadow-lg transition-all duration-200 flex flex-col gap-4">
                    <div className="w-12 h-12 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110" style={{ backgroundColor: role.bg }}>
                      <Icon size={22} style={{ color: role.color }} />
                    </div>
                    <div>
                      <div className="font-semibold text-ink text-sm mb-1" style={{ fontFamily: 'var(--font-display)' }}>{role.label}</div>
                      <div className="text-ink-faint text-xs leading-relaxed">{role.desc}</div>
                    </div>
                    <div className="text-teal text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity">Sign in →</div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <LandingChatbot open={chatOpen} setOpen={setChatOpen} msgs={chatMsgs} input={chatInput} setInput={setChatInput} onSend={sendChat} botTyping={botTyping} chatEndRef={chatEndRef} mode={chatMode} />
      </div>
    );
  }

  // Login / Register forms per role
  if (step === 'login' || step === 'register') {
    const isReg = step === 'register';
    return (
      <AuthShell onBack={() => goStep('select')} role={roleInfo}>
        <h2 className="text-2xl font-bold text-navy mb-1" style={{ fontFamily: 'var(--font-display)' }}>
          {isReg ? 'Create Account' : 'Sign In'}
        </h2>
        <p className="text-ink-muted text-sm mb-6">{isReg ? `Register as ${roleInfo?.label}` : `Welcome back, ${roleInfo?.label}`}</p>

        <form onSubmit={isReg ? handleRegister : handleLogin} className="space-y-4">
          {/* ADMIN */}
          {selectedRole === 'admin' && isReg && (
            <>
              <FormField label="Admin Username" value={form.username} onChange={v => setField('username', v)} placeholder="Choose a username" required />
              <FormField label="Email" type="email" value={form.email} onChange={v => setField('email', v)} placeholder="admin@hospital.com" required />
              <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Create a strong password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
              <OtpNotice phone={form.phone} />
            </>
          )}
          {selectedRole === 'admin' && !isReg && (
            <>
              <FormField label="Admin Username" value={form.username} onChange={v => setField('username', v)} placeholder="Your username" required />
              <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Your password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
              <OtpNotice phone={form.phone} />
            </>
          )}

          {/* DOCTOR */}
          {selectedRole === 'doctor' && isReg && (
            <>
              <FormField label="Username" value={form.username} onChange={v => setField('username', v)} placeholder="Choose a username" required />
              <div>
                <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Full Name</label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-teal font-semibold text-sm select-none">Dr.</span>
                  <input type="text" value={form.fullName} onChange={e => setField('fullName', e.target.value)} placeholder="Your full name" required
                    className="w-full bg-surface border border-rule rounded-xl pl-12 pr-4 py-3 text-ink text-sm placeholder:text-ink-faint focus:border-teal transition-colors" />
                </div>
              </div>
              <FormField label="Email" type="email" value={form.email} onChange={v => setField('email', v)} placeholder="doctor@hospital.com" required />
              <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
              <div>
                <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Specialty</label>
                <select value={form.specialty} onChange={e => setField('specialty', e.target.value)} required
                  className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm focus:border-teal transition-colors">
                  <option value="">Select your specialty</option>
                  {SPECIALTIES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Create a password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
            </>
          )}
          {selectedRole === 'doctor' && !isReg && (
            <>
              <FormField label="Username" value={form.username} onChange={v => setField('username', v)} placeholder="Your username" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Your password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
              <div>
                <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Specialty</label>
                <select value={form.specialty} onChange={e => setField('specialty', e.target.value)} required
                  className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm focus:border-teal transition-colors">
                  <option value="">Select your specialty</option>
                  {SPECIALTIES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </>
          )}

          {/* RECEPTIONIST */}
          {selectedRole === 'receptionist' && isReg && (
            <>
              <FormField label="Username" value={form.username} onChange={v => setField('username', v)} placeholder="Choose a username" required />
              <FormField label="Email" type="email" value={form.email} onChange={v => setField('email', v)} placeholder="reception@hospital.com" required />
              <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Create a password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
            </>
          )}
          {selectedRole === 'receptionist' && !isReg && (
            <>
              <FormField label="Username" value={form.username} onChange={v => setField('username', v)} placeholder="Your username" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder="Your password" required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
            </>
          )}

          {/* PATIENT */}
          {selectedRole === 'patient' && (
            <>
              <FormField label="Username" value={form.username} onChange={v => setField('username', v)} placeholder="Your username" required />
              <FormField label="Phone Number" value={form.phone} onChange={v => setField('phone', v)} placeholder="+1 (555) 000-0000" required />
              <FormField label="Password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={v => setField('password', v)} placeholder={isReg ? 'Create a password' : 'Your password'} required
                suffix={<button type="button" onClick={() => setShowPassword(s => !s)} className="text-ink-faint hover:text-ink transition-colors">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>}
              />
              {selectedRole === 'patient' && <OtpNotice phone={form.phone} />}
            </>
          )}

          {isReg && selectedRole !== 'patient' && staffCodeRequired && (
            <FormField label="Staff Access Code" type="password" value={form.staffCode} onChange={v => setField('staffCode', v)} placeholder="Given to you by the hospital administrator" required />
          )}
          {error && <div className="text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
          <button type="submit" disabled={busy} className="w-full bg-teal hover:bg-teal-light disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
            {busy ? 'Please wait…' : isReg
              ? (selectedRole === 'doctor' ? 'Next — Complete Profile' : 'Create Account')
              : (selectedRole === 'admin' || selectedRole === 'patient' ? 'Send OTP & Continue' : 'Sign In')}
          </button>
        </form>

        <div className="mt-5 text-center">
          <span className="text-ink-muted text-sm">{isReg ? 'Already have an account? ' : "Don't have an account? "}</span>
          <button onClick={() => goStep(isReg ? 'login' : 'register')} className="text-teal text-sm font-medium hover:underline">
            {isReg ? 'Sign In' : 'Register'}
          </button>
        </div>
        <div className="mt-4 pt-4 border-t border-rule text-center">
          <p className="text-xs text-ink-faint">
            {isReg && selectedRole !== 'patient' ? 'Staff accounts require the access code from your administrator.' : 'Your session is protected and expires automatically.'}
          </p>
        </div>
      </AuthShell>
    );
  }

  // Landing page
  return (
    <div className="min-h-full bg-navy flex flex-col overflow-y-auto">
      {/* Header */}
      <header className="px-8 py-4 flex items-center justify-between border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-teal rounded-xl flex items-center justify-center">
            <Activity size={18} className="text-white" />
          </div>
          <div>
            <div className="text-white font-bold text-base" style={{ fontFamily: 'var(--font-display)' }}>Helix HMS</div>
            <div className="text-white/40 text-xs">Smart Hospital Management</div>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <a href={`tel:${hospital.phone.replace(/[^+\d]/g, '')}`} className="flex items-center gap-2 text-white/60 hover:text-white text-sm transition-colors">
            <Phone size={14} />
            {hospital.phone}
          </a>
          <button
            onClick={() => setStep('select')}
            className="flex items-center gap-2 bg-teal hover:bg-teal-light text-white text-sm font-semibold px-5 py-2.5 rounded-xl transition-colors"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            Access Portal <ChevronRight size={14} />
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
        <div className="inline-flex items-center gap-2 bg-teal/10 border border-teal/30 text-teal text-xs font-medium px-4 py-1.5 rounded-full mb-6">
          <Activity size={12} />
          Smart Hospital Management System
        </div>
        <h1 className="text-5xl md:text-6xl font-bold text-white leading-tight mb-5 max-w-3xl" style={{ fontFamily: 'var(--font-display)' }}>
          Helix — Where Care Meets{' '}
          <span className="text-teal">Intelligence</span>
        </h1>
        <p className="text-white/60 text-lg max-w-xl leading-relaxed mb-10">
          A unified platform for doctors, staff, and patients. Real-time room management, smart scheduling, AI-assisted care — all in one place.
        </p>
        <div className="flex flex-wrap gap-3 justify-center">
          <button
            onClick={() => setStep('select')}
            className="flex items-center gap-2 bg-teal hover:bg-teal-light text-white font-semibold px-7 py-3.5 rounded-xl transition-colors text-base"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            Get Started <ChevronRight size={16} />
          </button>
          <button
            onClick={() => setChatOpen(true)}
            className="flex items-center gap-2 bg-white/10 hover:bg-white/20 text-white font-semibold px-7 py-3.5 rounded-xl transition-colors text-base border border-white/20"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            <Bot size={16} /> Talk to Helix AI
          </button>
        </div>
      </section>

      {/* Stats */}
      <section className="border-t border-white/10 px-8 py-8">
        <div className="max-w-4xl mx-auto grid grid-cols-2 gap-6 md:grid-cols-4">
          {[
            { icon: Stethoscope, label: 'Departments', value: pubStats.departments.toLocaleString() },
            { icon: Users, label: 'Doctors', value: pubStats.doctors.toLocaleString() },
            { icon: BedDouble, label: 'Beds Managed', value: pubStats.beds.toLocaleString() },
            { icon: Heart, label: 'Patients Served', value: pubStats.patientsServed.toLocaleString() },
          ].map(s => (
            <div key={s.label} className="text-center">
              <div className="w-10 h-10 bg-teal/10 rounded-xl flex items-center justify-center mx-auto mb-3">
                <s.icon size={18} className="text-teal" />
              </div>
              <div className="text-2xl font-bold text-white" style={{ fontFamily: 'var(--font-display)' }}>{s.value}</div>
              <div className="text-white/50 text-sm">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-white/10 px-8 py-12">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-2xl font-bold text-white text-center mb-8" style={{ fontFamily: 'var(--font-display)' }}>
            Built for Every Role
          </h2>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {roles.map(role => {
              const Icon = role.icon;
              return (
                <div key={role.id} className="bg-white/5 border border-white/10 rounded-2xl p-5 hover:bg-white/8 transition-colors">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-3" style={{ backgroundColor: role.bg + '22' }}>
                    <Icon size={18} style={{ color: role.color }} />
                  </div>
                  <div className="text-white font-semibold text-sm mb-1" style={{ fontFamily: 'var(--font-display)' }}>{role.label}</div>
                  <div className="text-white/40 text-xs leading-relaxed">{role.desc}</div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Contact */}
      <section className="border-t border-white/10 px-8 py-10">
        <div className="max-w-4xl mx-auto flex flex-wrap items-center justify-between gap-6">
          <div>
            <h3 className="text-white font-bold text-lg mb-1" style={{ fontFamily: 'var(--font-display)' }}>Need Help?</h3>
            <p className="text-white/50 text-sm">Our support team is available 24 / 7</p>
          </div>
          <div className="flex flex-wrap gap-4">
            {[
              { icon: Phone, label: hospital.phone, sub: '24/7 Helpline' },
              { icon: Ambulance, label: hospital.ambulance, sub: 'Emergency' },
              { icon: Mail, label: hospital.email, sub: 'Email Support' },
              { icon: Globe, label: hospital.website, sub: 'Website' },
            ].map(c => (
              <div key={c.label} className="flex items-center gap-3 bg-white/5 border border-white/10 rounded-xl px-4 py-3">
                <c.icon size={16} className="text-teal shrink-0" />
                <div>
                  <div className="text-white text-sm font-medium">{c.label}</div>
                  <div className="text-white/40 text-xs">{c.sub}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-white/10 px-8 py-4 text-center text-white/30 text-xs">
        © {new Date().getFullYear()} {hospital.name} · Smart Hospital Management System · All rights reserved
      </footer>

      <LandingChatbot open={chatOpen} setOpen={setChatOpen} msgs={chatMsgs} input={chatInput} setInput={setChatInput} onSend={sendChat} botTyping={botTyping} chatEndRef={chatEndRef} mode={chatMode} />
    </div>
  );
}

// ---- Sub-components ----

function OtpNotice({ phone }: { phone: string }) {
  return (
    <div className="flex items-start gap-2 bg-info-bg rounded-xl p-3">
      <Phone size={14} className="text-info mt-0.5 shrink-0" />
      <p className="text-xs text-ink-muted">
        An OTP will be sent to <span className="font-medium text-ink">{phone || 'your phone number'}</span> for verification.
      </p>
    </div>
  );
}

export function AuthShell({ children, onBack, role }: {
  children: React.ReactNode;
  onBack: () => void;
  role: typeof roles[0] | undefined;
}) {
  return (
    <div className="min-h-full bg-surface flex flex-col">
      <HelixHeader />
      <div className="flex-1 flex items-center justify-center px-4 py-10">
        <div className="bg-card rounded-2xl border border-rule shadow-sm w-full max-w-md p-8">
          <button onClick={onBack} className="flex items-center gap-1.5 text-ink-muted hover:text-ink text-sm mb-6 transition-colors">
            <ArrowLeft size={14} /> Back
          </button>
          {role && (
            <div className="flex items-center gap-3 mb-6 pb-6 border-b border-rule">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: role.bg }}>
                <role.icon size={18} style={{ color: role.color }} />
              </div>
              <div>
                <div className="font-semibold text-ink text-sm" style={{ fontFamily: 'var(--font-display)' }}>{role.label}</div>
                <div className="text-ink-faint text-xs">{role.desc}</div>
              </div>
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}

function HelixHeader() {
  return (
    <div className="bg-navy px-8 py-4 flex items-center gap-3">
      <div className="w-8 h-8 bg-teal rounded-lg flex items-center justify-center">
        <Activity size={16} className="text-white" />
      </div>
      <div>
        <span className="text-white font-bold text-base" style={{ fontFamily: 'var(--font-display)' }}>Helix HMS</span>
        <span className="text-white/40 text-xs ml-2">Smart Hospital Management</span>
      </div>
    </div>
  );
}

export function FormField({ label, value, onChange, placeholder, type = 'text', required, suffix }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; required?: boolean; suffix?: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">{label}</label>
      <div className="relative">
        <input
          type={type} value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} required={required}
          className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm placeholder:text-ink-faint focus:border-teal transition-colors pr-10"
        />
        {suffix && <div className="absolute right-3 top-1/2 -translate-y-1/2">{suffix}</div>}
      </div>
    </div>
  );
}

interface ChatbotProps {
  open: boolean; setOpen: (v: boolean) => void;
  msgs: ChatMsg[]; input: string; setInput: (v: string) => void;
  onSend: () => void; botTyping: boolean;
  chatEndRef: React.RefObject<HTMLDivElement | null>;
  mode: 'ollama' | 'basic';
}

function LandingChatbot({ open, setOpen, msgs, input, setInput, onSend, botTyping, chatEndRef, mode }: ChatbotProps) {
  const quickReplies = ['🚑 Book ambulance', '💊 Health advice', '📅 Book appointment', '📞 Contact info'];

  return (
    <>
      {open && (
        <div className="fixed bottom-20 right-6 w-80 bg-card border border-rule rounded-2xl shadow-2xl flex flex-col overflow-hidden z-50" style={{ height: '440px' }}>
          <div className="bg-navy px-4 py-3 flex items-center gap-3">
            <div className="w-8 h-8 bg-teal rounded-xl flex items-center justify-center shrink-0">
              <Bot size={16} className="text-white" />
            </div>
            <div className="flex-1">
              <div className="text-white text-sm font-semibold" style={{ fontFamily: 'var(--font-display)' }}>Helix AI</div>
              <div className="text-white/50 text-xs flex items-center gap-1">
                <span className={`w-1.5 h-1.5 rounded-full inline-block ${mode === 'ollama' ? 'bg-success' : 'bg-warning'}`} />
                {mode === 'ollama' ? 'Online · Ambulance & Health Guide' : 'Basic mode · AI model offline'}
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-white/50 hover:text-white transition-colors">
              <X size={16} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {msgs.map(msg => (
              <div key={msg.id} className={`flex gap-2 ${msg.from === 'user' ? 'flex-row-reverse' : ''}`}>
                {msg.from === 'bot' && (
                  <div className="w-6 h-6 bg-teal-muted rounded-full flex items-center justify-center shrink-0 mt-0.5">
                    <Bot size={12} className="text-teal" />
                  </div>
                )}
                <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed whitespace-pre-line ${
                  msg.from === 'bot' ? 'bg-surface text-ink rounded-tl-sm' : 'bg-navy text-white rounded-tr-sm'
                }`}>
                  {renderInline(msg.text)}
                </div>
              </div>
            ))}
            {botTyping && (
              <div className="flex gap-2">
                <div className="w-6 h-6 bg-teal-muted rounded-full flex items-center justify-center shrink-0">
                  <Bot size={12} className="text-teal" />
                </div>
                <div className="bg-surface rounded-2xl rounded-tl-sm px-3 py-2 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 bg-ink-faint rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-ink-faint rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-ink-faint rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="px-3 pb-1 flex gap-1.5 overflow-x-auto">
            {quickReplies.map(q => (
              <button key={q} onClick={() => { setInput(q.replace(/^[^\s]+\s/, '')); }}
                className="text-xs text-teal bg-teal-muted hover:bg-teal hover:text-white px-2.5 py-1 rounded-full whitespace-nowrap transition-all shrink-0 font-medium"
                style={{ fontFamily: 'var(--font-display)' }}>
                {q}
              </button>
            ))}
          </div>

          <div className="px-3 py-3 border-t border-rule flex gap-2">
            <input
              type="text" value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && onSend()}
              placeholder="Ask Helix AI..."
              className="flex-1 bg-surface border border-rule rounded-xl px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-teal transition-colors"
            />
            <button onClick={onSend} disabled={!input.trim() || botTyping}
              className="w-8 h-8 bg-teal hover:bg-teal-light disabled:opacity-40 text-white rounded-xl flex items-center justify-center transition-all shrink-0">
              <Send size={13} />
            </button>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen(!open)}
        className="fixed bottom-6 right-6 w-14 h-14 bg-teal hover:bg-teal-light text-white rounded-2xl shadow-lg flex items-center justify-center transition-all hover:scale-105 z-50"
      >
        {open ? <X size={22} /> : <Bot size={22} />}
        {!open && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-danger rounded-full flex items-center justify-center">
            <HelpCircle size={10} className="text-white" />
          </span>
        )}
      </button>
    </>
  );
}

/** Shown right after a patient signs up (and verifies the OTP): collects the details the doctors and the AI queue need. */
export function PatientProfileSetup({ user, onDone, onLogout }: { user: AuthUser; onDone: (u: AuthUser) => void; onLogout: () => void }) {
  const role = roles.find(r => r.id === 'patient');
  const [f, setF] = useState({ name: '', age: '', gender: 'female', bloodType: '', address: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF(x => ({ ...x, [k]: v }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await api.patch('/patients/me', { name: f.name, age: f.age ? Number(f.age) : null, gender: f.gender, bloodType: f.bloodType, address: f.address });
      const me = await api.get<{ user: AuthUser }>('/auth/me');
      onDone(me.user);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  return (
    <AuthShell onBack={onLogout} role={role}>
      <h2 className="text-2xl font-bold text-navy mb-1" style={{ fontFamily: 'var(--font-display)' }}>Your Profile</h2>
      <p className="text-ink-muted text-sm mb-6">Welcome, {user.username}! A few details help doctors care for you.</p>
      <form onSubmit={submit} className="space-y-4">
        <FormField label="Full Name" value={f.name} onChange={v => set('name', v)} placeholder="Your full name" required />
        <div className="grid grid-cols-2 gap-3">
          <FormField label="Age" type="number" value={f.age} onChange={v => set('age', v)} placeholder="e.g. 34" required />
          <div>
            <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Gender</label>
            <select value={f.gender} onChange={e => set('gender', e.target.value)} className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm focus:border-teal transition-colors">
              <option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-ink-muted mb-1.5 uppercase tracking-wide">Blood Type</label>
          <select value={f.bloodType} onChange={e => set('bloodType', e.target.value)} className="w-full bg-surface border border-rule rounded-xl px-4 py-3 text-ink text-sm focus:border-teal transition-colors">
            <option value="">Not sure</option>
            {['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'].map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
        <FormField label="Address" value={f.address} onChange={v => set('address', v)} placeholder="Street, city" />
        {error && <div className="text-xs text-danger bg-danger-bg rounded-xl px-3 py-2.5">{error}</div>}
        <button type="submit" disabled={busy} className="w-full bg-teal hover:bg-teal-light disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors" style={{ fontFamily: 'var(--font-display)' }}>
          {busy ? 'Saving…' : 'Save & Continue'}
        </button>
      </form>
    </AuthShell>
  );
}
