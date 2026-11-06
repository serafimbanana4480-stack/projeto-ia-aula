"use client";

import { useEffect, useState } from "react";

/**
 * Subscribe to a CSS media query without breaking SSR.
 *
 * The first render always reports `false` so server and client markup agree;
 * the real value is committed in an effect. Components that must hide
 * themselves from assistive tech on mobile (drawers, overlays) should use this
 * to decide *when* they are actually hidden — gating `inert`/`aria-hidden` on
 * a boolean that is true on desktop makes an entire navigation unfocusable.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

export default useMediaQuery;
