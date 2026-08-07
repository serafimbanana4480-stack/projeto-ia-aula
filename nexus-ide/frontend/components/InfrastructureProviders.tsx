"use client";

/**
 * NEXUS IDE — Infrastructure Providers Wrapper
 *
 * Loads global infrastructure components like the Advanced Mode selector
 * that need to exist above the page layout but below the auth guard.
 */
import { useEffect } from "react";
import dynamic from "next/dynamic";

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
  return (
    <>
      {children}
      {/* Floating Advanced Mode button — rendered above all pages */}
      <div className="fixed bottom-6 left-6 z-50">
        <AdvancedModePanel />
      </div>
    </>
  );
}
