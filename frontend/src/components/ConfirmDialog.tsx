import { AlertTriangle, Info, CheckCircle, X } from 'lucide-react';

type Variant = 'danger' | 'warning' | 'info' | 'success';

interface Props {
  open: boolean;
  variant?: Variant;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const config: Record<Variant, { icon: React.ComponentType<{ size?: number; className?: string }>; iconClass: string; confirmClass: string; bg: string; border: string }> = {
  danger: {
    icon: AlertTriangle,
    iconClass: 'text-danger',
    confirmClass: 'bg-danger hover:bg-red-600 text-white',
    bg: 'bg-danger-bg',
    border: 'border-danger/30',
  },
  warning: {
    icon: AlertTriangle,
    iconClass: 'text-warning',
    confirmClass: 'bg-warning hover:bg-amber-500 text-white',
    bg: 'bg-warning-bg',
    border: 'border-warning/30',
  },
  info: {
    icon: Info,
    iconClass: 'text-info',
    confirmClass: 'bg-teal hover:bg-teal-light text-white',
    bg: 'bg-info-bg',
    border: 'border-info/30',
  },
  success: {
    icon: CheckCircle,
    iconClass: 'text-success',
    confirmClass: 'bg-success hover:bg-emerald-600 text-white',
    bg: 'bg-success-bg',
    border: 'border-success/30',
  },
};

export default function ConfirmDialog({
  open, variant = 'danger', title, message,
  confirmLabel = 'Confirm', cancelLabel = 'Cancel',
  onConfirm, onCancel,
}: Props) {
  if (!open) return null;
  const c = config[variant];
  const Icon = c.icon;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onCancel}>
      <div
        className="bg-card rounded-2xl border border-rule shadow-2xl w-full max-w-sm overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Coloured top strip */}
        <div className={`${c.bg} ${c.border} border-b px-6 py-5 flex items-start gap-4`}>
          <div className={`w-10 h-10 rounded-xl ${c.bg} flex items-center justify-center shrink-0 border ${c.border}`}>
            <Icon size={20} className={c.iconClass} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-bold text-ink text-base leading-tight" style={{ fontFamily: 'var(--font-display)' }}>{title}</h3>
            <p className="text-ink-muted text-sm mt-1 leading-relaxed">{message}</p>
          </div>
          <button onClick={onCancel} className="text-ink-faint hover:text-ink transition-colors shrink-0 mt-0.5">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-4 flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-rule text-sm text-ink-muted hover:bg-surface transition-colors"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={() => { onConfirm(); }}
            className={`flex-1 py-2.5 rounded-xl text-sm font-semibold transition-colors ${c.confirmClass}`}
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
