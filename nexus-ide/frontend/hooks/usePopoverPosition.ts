"use client";

import { useLayoutEffect, useState, type CSSProperties, type RefObject } from "react";

/** Keep composer menus inside the visible viewport, including above a mobile keyboard. */
export function usePopoverPosition(
  open: boolean,
  anchor: RefObject<HTMLElement | null>,
  placement: "above" | "below",
  width: number,
): CSSProperties {
  const [position, setPosition] = useState<CSSProperties | null>(null);

  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const update = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const viewport = window.visualViewport;
      const top = viewport?.offsetTop ?? 0;
      const height = viewport?.height ?? window.innerHeight;
      const viewportWidth = viewport?.width ?? window.innerWidth;
      const menuWidth = Math.min(width, viewportWidth - 24);
      const above = rect.top - top - 8;
      const below = top + height - rect.bottom - 8;
      const showAbove = placement === "above" ? above >= 160 || above >= below : below < 160 && above > below;
      const next: CSSProperties = {
        position: "fixed",
        width: menuWidth,
        left: Math.max(12, Math.min(rect.right - menuWidth, viewportWidth - menuWidth - 12)),
        ...(showAbove
          ? { bottom: window.innerHeight - rect.top + 8 }
          : { top: rect.bottom + 8 }),
        maxHeight: Math.max(0, Math.min(520, (showAbove ? above : below) - 12)),
        zIndex: 60,
      };
      setPosition((current) => current && Object.keys(next).every((key) => current[key as keyof CSSProperties] === next[key as keyof CSSProperties]) ? current : next);
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      window.visualViewport?.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("scroll", update);
    };
  }, [open, anchor, placement, width]);

  return open ? position ?? { visibility: "hidden" } : {};
}
