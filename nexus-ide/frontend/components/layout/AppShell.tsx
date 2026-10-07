"use client";

import type { ReactNode } from "react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import BottomHUD from "./BottomHUD";

/**
 * AppShell — single owner of the application chrome.
 *
 * Composes Sidebar + TopBar + the scrollable content area + an optional
 * right rail + BottomHUD, in the same arrangement every page used to
 * hand-roll individually: a full-width top bar, a full-width bottom HUD,
 * and a Sidebar/content row sandwiched between them.
 *
 * WHY A SHARED COMPONENT INSTEAD OF AN `app/(app)/layout.tsx` ROUTE GROUP:
 * Moving ~20 existing page directories into a new route group would touch
 * every affected route's file path in a Next 15 App Router tree where
 * `app/page.tsx` is already the chat route and several segments ship their
 * own `loading.tsx` / `error.tsx` special files that must move in lock-step.
 * That is a large, easy-to-get-subtly-wrong diff (broken relative imports,
 * misplaced special files, route-group naming edge cases). Swapping each
 * page's hand-rolled `<TopBar/><Sidebar/><BottomHUD/>` scaffold for
 * `<AppShell>` achieves the identical rendered result with a much smaller,
 * more easily verified diff — no files move, no route paths change. That
 * makes this the lower-risk path, so it's the one used here.
 */

export interface AppShellProps {
  children: ReactNode;
  /** Optional right-hand rail (e.g. a context/agent-activity panel). */
  rightRail?: ReactNode;
  /** Hide the top bar. Defaults to visible. */
  showTopBar?: boolean;
  /** Hide the bottom system HUD. Defaults to visible. */
  showBottomHUD?: boolean;
  /** Page name shown as a breadcrumb next to the NEXUS IDE brand. */
  title?: string;
  /**
   * Escape hatch for pages that manage their own full-bleed layout and
   * internal scroll regions (editor, documents, dashboard, mission control,
   * swarm…). Drops the default content padding in favour of a container
   * that clips horizontal overflow and lets the page's own content decide
   * how it scrolls vertically.
   */
  noPadding?: boolean;
  /**
   * Element used for the scroll container. Defaults to the semantic
   * `<main>` landmark. Pages whose own content already renders its own
   * `<main>` (e.g. the dashboard) should pass `"div"` to avoid nesting two
   * `<main>` landmarks on the same page.
   */
  mainAs?: "main" | "div";
}

export default function AppShell({
  children,
  rightRail,
  showTopBar = true,
  showBottomHUD = true,
  title,
  noPadding = false,
  mainAs = "main",
}: AppShellProps) {
  // Mirrors the `as`-cast trick already used in components/ui/Surface.tsx:
  // narrow the union to one concrete intrinsic tag so JSX accepts a
  // dynamically-chosen element while the runtime string can be either value.
  const MainTag = mainAs as "main";

  return (
    <div className="nx-ambient flex h-dvh min-h-0 flex-col overflow-hidden bg-nexus-bg text-nexus-text">
      {showTopBar && <TopBar title={title} />}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar />

        <MainTag
          className={
            noPadding
              ? "min-w-0 flex-1 overflow-y-auto overflow-x-hidden"
              : "min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-6 lg:p-7"
          }
        >
          {children}
        </MainTag>

        {rightRail ? (
          <aside className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-nexus-border/60 bg-nexus-panel xl:block">
            {rightRail}
          </aside>
        ) : null}
      </div>

      {showBottomHUD && <BottomHUD />}
    </div>
  );
}
