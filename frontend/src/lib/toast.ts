import { useCallback, useRef, useState } from 'react';

export type ToastVariant = 'success' | 'danger' | 'warning' | 'info';

/** const { toast, notify } = useToast();  ...  <Toast {...toast} />   notify('Saved'); notify(err.message, 'danger') */
export function useToast() {
  const [toast, setToast] = useState<{ show: boolean; message: string; variant: ToastVariant }>({ show: false, message: '', variant: 'success' });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const notify = useCallback((message: string, variant: ToastVariant = 'success') => {
    clearTimeout(timer.current);
    setToast({ show: true, message, variant });
    timer.current = setTimeout(() => setToast(t => ({ ...t, show: false })), 3800);
  }, []);
  return { toast, notify };
}
