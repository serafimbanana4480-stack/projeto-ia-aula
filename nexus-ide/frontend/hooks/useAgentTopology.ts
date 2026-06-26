import { useQuery } from "@tanstack/react-query";
import { apiUrl } from "../lib/api";

interface AgentNode {
  id: string;
  label: string;
  x: number;
  y: number;
  color: string;
  status: "idle" | "active" | "error" | "busy" | "offline";
  size: number;
  cpu?: number | null;
  memory?: number | null;
}

interface AgentLink {
  source: string;
  target: string;
  value: number;
  active?: boolean;
}

interface TopologyData {
  nodes: AgentNode[];
  links: AgentLink[];
}

export function useAgentTopology() {
  return useQuery<TopologyData>({
    queryKey: ["agentTopology"],
    queryFn: async () => {
      const res = await fetch(apiUrl("/api/agents/topology"));
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      return res.json();
    },
    refetchInterval: 10000, // 10 seconds (same as before)
  });
}
