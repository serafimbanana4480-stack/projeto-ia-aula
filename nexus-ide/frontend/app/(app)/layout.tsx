import { SidebarPro } from "@/components/SidebarPro";
import { ContextualHelp } from "@/components/ContextualHelp";

export const metadata = {
  title: "NEXUS IDE",
  description: "IDE assistida por IA",
};

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <SidebarPro />

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Contextual Help */}
        <ContextualHelp currentView={typeof window !== 'undefined' ? window.location.pathname : ''} />

        {/* Page Content */}
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
