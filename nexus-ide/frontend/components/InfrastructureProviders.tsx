"use client";

/**
 * NEXUS IDE — Infrastructure Providers Wrapper
 *
 * Loads global infrastructure components like the Advanced Mode selector
 * that need to exist above the page layout but below the auth guard.
 */
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";

// Load the AdvancedModePanel only when needed (code-split)
const AdvancedModePanel = dynamic(
  () => import("../components/chat/AdvancedModeSelector"),
  { ssr: false }
);

export default function InfrastructureProviders({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <>
      {children}
      {/* Floating Advanced Mode button: bottom-right, above the status HUD, so it never covers the sidebar footer. */}
      <div className={pathname === "/" || pathname === "/bots" ? "hidden" : "fixed bottom-12 right-5 z-50"}>
        <AdvancedModePanel />
      </div>
    </>
  );
}
