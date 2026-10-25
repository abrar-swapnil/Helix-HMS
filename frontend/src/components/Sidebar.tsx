import {
  Shield, UserRound, Stethoscope, ClipboardList, LogOut, ChevronRight,
  LayoutDashboard, Home, Users, BarChart3, CalendarDays, Search,
  MessageSquare, Clock, Activity,
} from 'lucide-react';
import type { Role, AuthUser } from '../types';

interface NavItem {
  id: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const navItems: Record<Role, NavItem[]> = {
  admin: [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'rooms', label: 'Rooms', icon: Home },
    { id: 'doctors', label: 'Doctors', icon: Users },
    { id: 'statistics', label: 'Statistics', icon: BarChart3 },
  ],
  receptionist: [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'rooms', label: 'Rooms', icon: Home },
    { id: 'patients', label: 'Patients', icon: UserRound },
    { id: 'appointments', label: 'Appointments', icon: CalendarDays },
    { id: 'doctors', label: 'Doctors', icon: Users },
  ],
  doctor: [
    { id: 'dashboard', label: 'My Dashboard', icon: LayoutDashboard },
    { id: 'waiting', label: 'Waiting List', icon: Clock },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  ],
  patient: [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'appointments', label: 'Appointments', icon: CalendarDays },
    { id: 'doctors', label: 'Find Doctors', icon: Search },
    { id: 'chatbot', label: 'MediAssist', icon: MessageSquare },
  ],
};

const roleIcons: Record<Role, React.ComponentType<{ size?: number }>> = {
  admin: Shield,
  receptionist: ClipboardList,
  doctor: Stethoscope,
  patient: UserRound,
};

const roleColors: Record<Role, string> = {
  admin: '#EEF4FF',
  receptionist: '#E0F5F5',
  doctor: '#D1FAE5',
  patient: '#FEF3C7',
};

const roleAccents: Record<Role, string> = {
  admin: '#3B82F6',
  receptionist: '#06A4A8',
  doctor: '#10B981',
  patient: '#F59E0B',
};

interface Props {
  user: AuthUser;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout: () => void;
}

export default function Sidebar({ user, activeView, onNavigate, onLogout }: Props) {
  const items = navItems[user.role];
  const RoleIcon = roleIcons[user.role];
  const roleColor = roleColors[user.role];
  const accentColor = roleAccents[user.role];

  return (
    <aside className="w-64 bg-navy flex flex-col h-full shrink-0">
      <div className="px-5 py-4 border-b border-navy-light">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 bg-teal rounded-lg flex items-center justify-center shrink-0">
            <Activity size={14} className="text-white" />
          </div>
          <div>
            <div className="text-white font-bold text-sm" style={{ fontFamily: 'var(--font-display)' }}>Helix HMS</div>
          </div>
        </div>
      </div>

      <div className="px-4 py-3 border-b border-navy-light">
        <div className="flex items-center gap-3 bg-navy-light rounded-xl p-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: roleColor }}>
            <span style={{ color: accentColor }}><RoleIcon size={16} /></span>
          </div>
          <div className="min-w-0">
            <div className="text-white text-sm font-medium truncate" style={{ fontFamily: 'var(--font-display)' }}>{user.name}</div>
            <div className="text-white/50 text-xs capitalize">{user.role}</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {items.map(item => {
          const isActive = activeView === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-150 group ${
                isActive
                  ? 'bg-teal text-white'
                  : 'text-white/60 hover:text-white hover:bg-navy-light'
              }`}
              style={{ fontFamily: 'var(--font-display)' }}
            >
              <span className={isActive ? 'text-white' : 'text-white/50 group-hover:text-white/80'}>
                <Icon size={16} />
              </span>
              <span className="flex-1 text-left">{item.label}</span>
              {isActive && <ChevronRight size={14} className="opacity-60" />}
            </button>
          );
        })}
      </nav>

      <div className="px-3 pb-4">
        <button
          onClick={onLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-white/50 hover:text-white hover:bg-danger/20 text-sm transition-all duration-150"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
