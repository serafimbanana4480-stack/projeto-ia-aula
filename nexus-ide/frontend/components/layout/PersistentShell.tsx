"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import AppShell from "./AppShell";
import { resolveShellConfig } from "./shellRouteConfig";

/**
 * Keeps Sidebar + TopBar + BottomHUD mounted across client navigations.
 * Pages under this shell render only their content (no per-page AppShell).
 */
export default function PersistentShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const config = resolveShellConfig(pathname);

  if (!config) {
    return <>{children}</>;
  }

  const { title, noPadding, mainAs, showTopBar, showBottomHUD } = config;

  return (
    <AppShell
      title={title}
      noPadding={noPadding}
      mainAs={mainAs}
      showTopBar={showTopBar}
      showBottomHUD={showBottomHUD}
    >
      {children}
    </AppShell>
  );
}
