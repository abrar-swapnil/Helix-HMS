import { useCallback, useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import type { AuthUser, Role } from './types';
import { api } from './lib/api';
import { LiveProvider } from './lib/live';
import Login, { PatientProfileSetup } from './components/Login';
import Sidebar from './components/Sidebar';
import AdminDashboard from './components/admin/AdminDashboard';
import DoctorDashboard from './components/doctor/DoctorDashboard';
import ReceptionistDashboard from './components/receptionist/ReceptionistDashboard';
import PatientDashboard from './components/patient/PatientDashboard';

const defaultViews: Record<Role, string> = {
  admin: 'overview',
  receptionist: 'dashboard',
  doctor: 'dashboard',
  patient: 'dashboard',
};

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [booting, setBooting] = useState(true);
  const [activeView, setActiveView] = useState('');

  const enter = useCallback((u: AuthUser) => {
    setUser(u);
    const saved = sessionStorage.getItem(`helix:view:${u.role}`);
    setActiveView(saved || defaultViews[u.role]);
  }, []);

  // Restore the session after a page refresh (the login cookie is HttpOnly, so ask the server who we are).
  useEffect(() => {
    api.get<{ user: AuthUser }>('/auth/me').then(r => enter(r.user)).catch(() => {}).finally(() => setBooting(false));
  }, [enter]);

  // Any API call that comes back "401 not signed in" (expired session, account disabled) returns to the login page.
  useEffect(() => {
    const onExpired = () => { setUser(null); setActiveView(''); };
    window.addEventListener('helix:unauthorized', onExpired);
    return () => window.removeEventListener('helix:unauthorized', onExpired);
  }, []);

  const navigate = (view: string) => {
    setActiveView(view);
    if (user) sessionStorage.setItem(`helix:view:${user.role}`, view);
  };

  const handleLogout = async () => {
    try { await api.post('/auth/logout'); } catch { /* ignore */ }
    sessionStorage.clear();
    setUser(null);
    setActiveView('');
  };

  if (booting) {
    return (
      <div className="h-full bg-navy flex items-center justify-center">
        <div className="w-12 h-12 bg-teal rounded-2xl flex items-center justify-center animate-pulse"><Activity size={22} className="text-white" /></div>
      </div>
    );
  }

  if (!user) return <Login onLogin={enter} />;

  // A patient who just registered must fill in their profile (name, age ...) before using the app.
  if (user.role === 'patient' && user.profileComplete === false) {
    return <PatientProfileSetup user={user} onDone={setUser} onLogout={handleLogout} />;
  }

  return (
    <LiveProvider>
      <div className="h-full flex overflow-hidden">
        <Sidebar user={user} activeView={activeView} onNavigate={navigate} onLogout={handleLogout} />

        <main className="flex-1 flex flex-col overflow-hidden bg-surface">
          {user.role === 'admin' && <AdminDashboard user={user} activeView={activeView} />}
          {user.role === 'doctor' && <DoctorDashboard user={user} activeView={activeView} />}
          {user.role === 'receptionist' && <ReceptionistDashboard user={user} activeView={activeView} />}
          {user.role === 'patient' && <PatientDashboard user={user} activeView={activeView} />}
        </main>
      </div>
    </LiveProvider>
  );
}
