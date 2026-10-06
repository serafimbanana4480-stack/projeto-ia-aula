"use client";

import { Infinity } from "lucide-react";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";
import { InfinitySuiteWorkspace } from "../infinity/InfinitySuiteWorkspace";
import { Surface, SurfaceHeader } from "../ui/Surface";

/** The dashboard and global panel share server-confirmed state and actions. */
export default function InfinitySuiteWidget() {
  const { activeModeIds, modes } = useAdvancedModeStore();

  return (
    <Surface elevation={1} padding="lg" className="nx-dashboard-widget flex flex-col">
      <SurfaceHeader
        icon={<Infinity className="h-4 w-4" />}
        tone={activeModeIds.length > 0 ? "accent" : "neutral"}
        title="Infinity Suite"
        subtitle="Escolhe a estratégia, prepara o pedido e consulta os limites reais."
        action={
          <span className="rounded-full bg-purple-400/10 px-2.5 py-1 text-[10px] font-semibold text-purple-300">
            {activeModeIds.length}/{Object.keys(modes).length || "—"} configurados
          </span>
        }
      />
      <div className="mt-5"><InfinitySuiteWorkspace compact /></div>
    </Surface>
  );
}
