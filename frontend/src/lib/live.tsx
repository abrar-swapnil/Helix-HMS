/**
 * lib/live.tsx - live data for every screen.
 *
 * The backend pushes a tiny "doctors / appointments / rooms ... changed" signal over Server-Sent Events whenever
 * ANYONE (admin, receptionist, doctor, patient) changes something. Each screen re-fetches just the lists it shows
 * through the normal, permission-checked API. That is what keeps the four role interfaces in sync with the database.
 *
 * Safety nets: also refreshes on a timer (waiting times / AI priorities change as time passes), when the tab becomes
 * visible again, and after the event stream reconnects.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { errorMessage } from './api';

type Listener = (entities: string[]) => void;
const LiveContext = createContext<{ subscribe: (fn: Listener) => () => void }>({ subscribe: () => () => {} });

export function LiveProvider({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  useEffect(() => {
    const es = new EventSource('/api/events');
    const fire = (entities: string[]) => listeners.current.forEach(l => l(entities));
    es.addEventListener('changed', e => {
      try { fire(JSON.parse((e as MessageEvent).data).entities ?? ['*']); } catch { fire(['*']); }
    });
    es.addEventListener('hello', () => fire(['*']));            // (re)connected: catch up on anything we missed
    return () => es.close();
  }, []);
  const subscribe = useCallback((fn: Listener) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);
  return <LiveContext.Provider value={{ subscribe }}>{children}</LiveContext.Provider>;
}

export function useLiveQuery<T>(
  fetcher: () => Promise<T>,
  entities: string[],
  opts: { pollMs?: number; enabled?: boolean } = {},
) {
  const { subscribe } = useContext(LiveContext);
  const { pollMs = 20000, enabled = true } = opts;
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const entityKey = entities.join(',');
  const alive = useRef(true);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const result = await fetcherRef.current();
      if (alive.current && mine === seq.current) { setData(result); setError(''); }
    } catch (e) {
      if (alive.current && mine === seq.current) setError(errorMessage(e));
    } finally {
      if (alive.current && mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!enabled) return () => { alive.current = false; };
    reload();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const debounced = () => { clearTimeout(timer); timer = setTimeout(reload, 150); };
    const unsub = subscribe(ents => {
      if (ents.includes('*') || entityKey.split(',').some(e => ents.includes(e))) debounced();
    });
    const poll = setInterval(reload, pollMs);
    const onVisible = () => { if (document.visibilityState === 'visible') reload(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive.current = false;
      clearTimeout(timer);
      clearInterval(poll);
      unsub();
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled, entityKey, pollMs, reload, subscribe]);

  return { data, loading, error, reload, setData };
}
