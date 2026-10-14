import { useEffect, useRef } from 'react';

// A completed request may still create a run, but must not redirect a user who
// already left this screen. The run remains available in history.
export function useMounted() {
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  return mounted;
}
