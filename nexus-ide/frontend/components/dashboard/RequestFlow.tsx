"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl } from "../../lib/api";

interface FlowNode {
  id: string;
  label: string;
  type: "source" | "process" | "destination";
  value: number;
  color: string;
}

interface FlowLink {
  source: string;
  target: string;
  value: number;
  latency_ms: number;
}

interface FlowData {
  available?: boolean;
  reason?: string;
  nodes: FlowNode[];
  links: FlowLink[];
  summary: {
    total_requests: number;
    successful_requests: number;
    failed_requests: number;
    avg_latency_ms: number;
    throughput_tps: number;
  };
}

export default function RequestFlow() {
  const [flowData, setFlowData] = useState<FlowData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchFlowData = async () => {
      try {
        setLoading(true);
        const response = await fetch(apiUrl("/api/metrics/flow"));
        const data = await response.json();
        setFlowData(data);
      } catch (error) {
        console.error("Failed to fetch flow data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchFlowData();

    // Refresh every 30 seconds
    const interval = setInterval(fetchFlowData, 30000);

    return () => clearInterval(interval);
  }, []);

  const getNodePosition = (nodeId: string) => {
    const positions: Record<string, { x: number; y: number }> = {
      user: { x: 50, y: 100 },
      router: { x: 200, y: 100 },
      agent: { x: 350, y: 100 },
      llm: { x: 500, y: 100 },
    };
    return positions[nodeId] || { x: 0, y: 0 };
  };

  const formatLatency = (ms: number) => {
    if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-3 text-sm font-semibold">Fluxo de Requisições</div>

      {loading ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 items-center justify-center text-xs text-gray-500"
        >
          Carregando...
        </motion.div>
      ) : flowData?.available === false ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-48 flex-col items-center justify-center gap-3 text-center text-xs text-gray-500"
        >
          <svg className="h-10 w-10 text-nexus-border" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="5" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="19" cy="12" r="2" />
            <path d="M7 12h3M14 12h3" />
          </svg>
          <div className="font-medium text-gray-400">Rastreamento de fluxo indisponível</div>
          <div className="max-w-md text-gray-600">
            {flowData.reason ??
              "O backend ainda não instrumentou o rastreamento distribuído de requisições."}
          </div>
          {flowData.summary && (
            <div className="mt-2 grid grid-cols-4 gap-3 rounded-lg border border-nexus-border/50 bg-nexus-border/20 px-4 py-2 text-gray-400">
              <div className="text-center">
                <div className="text-gray-600">Total</div>
                <div className="font-semibold">{flowData.summary.total_requests}</div>
              </div>
              <div className="text-center">
                <div className="text-gray-600">OK</div>
                <div className="font-semibold text-green-400">{flowData.summary.successful_requests}</div>
              </div>
              <div className="text-center">
                <div className="text-gray-600">Fail</div>
                <div className="font-semibold text-red-400">{flowData.summary.failed_requests}</div>
              </div>
              <div className="text-center">
                <div className="text-gray-600">Latência</div>
                <div className="font-semibold">{formatLatency(flowData.summary.avg_latency_ms)}</div>
              </div>
            </div>
          )}
        </motion.div>
      ) : flowData ? (
        <div>
          <svg className="h-48 w-full" viewBox="0 0 600 200">
            <defs>
              <marker
                id="arrowhead"
                markerWidth="10"
                markerHeight="7"
                refX="9"
                refY="3.5"
                orient="auto"
              >
                <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
              </marker>
            </defs>

            {/* Links */}
            {flowData.links.map((link, index) => {
              const sourcePos = getNodePosition(link.source);
              const targetPos = getNodePosition(link.target);
              const midX = (sourcePos.x + targetPos.x) / 2;
              const midY = (sourcePos.y + targetPos.y) / 2;

              return (
                <g key={`${link.source}-${link.target}`}>
                  <motion.path
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ duration: 1, delay: index * 0.2 }}
                    d={`M ${sourcePos.x} ${sourcePos.y} L ${targetPos.x} ${targetPos.y}`}
                    stroke="#6b7280"
                    strokeWidth={2}
                    fill="none"
                    markerEnd="url(#arrowhead)"
                    opacity={0.5}
                  />
                  <motion.text
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: index * 0.2 + 0.5 }}
                    x={midX}
                    y={midY - 10}
                    textAnchor="middle"
                    fontSize={10}
                    fill="#9ca3af"
                  >
                    {link.value > 0 ? link.value : "0"}
                  </motion.text>
                  <motion.text
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: index * 0.2 + 0.7 }}
                    x={midX}
                    y={midY + 15}
                    textAnchor="middle"
                    fontSize={9}
                    fill="#6b7280"
                  >
                    {formatLatency(link.latency_ms)}
                  </motion.text>
                </g>
              );
            })}

            {/* Nodes */}
            {flowData.nodes.map((node, index) => {
              const pos = getNodePosition(node.id);
              return (
                <g key={node.id}>
                  <motion.circle
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: index * 0.3 + 0.5 }}
                    cx={pos.x}
                    cy={pos.y}
                    r={30}
                    fill={node.color}
                    opacity={0.2}
                  />
                  <motion.circle
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: index * 0.3 + 0.6 }}
                    cx={pos.x}
                    cy={pos.y}
                    r={25}
                    fill={node.color}
                    opacity={0.4}
                  />
                  <motion.text
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: index * 0.3 + 0.8 }}
                    x={pos.x}
                    y={pos.y + 4}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight="bold"
                    fill="#e6edf3"
                  >
                    {node.label}
                  </motion.text>
                  <motion.text
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: index * 0.3 + 1 }}
                    x={pos.x}
                    y={pos.y + 20}
                    textAnchor="middle"
                    fontSize={9}
                    fill="#9ca3af"
                  >
                    {node.value > 0 ? node.value : "0"}
                  </motion.text>
                </g>
              );
            })}
          </svg>

          {/* Summary */}
          <div className="mt-3 grid grid-cols-4 gap-2 border-t border-nexus-border/50 pt-2">
            <div className="text-center">
              <div className="text-xs text-gray-500">Total</div>
              <div className="text-sm font-semibold">
                {flowData.summary.total_requests}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-500">Sucesso</div>
              <div className="text-sm font-semibold text-green-400">
                {flowData.summary.successful_requests}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-500">Falha</div>
              <div className="text-sm font-semibold text-red-400">
                {flowData.summary.failed_requests}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-500">Latência</div>
              <div className="text-sm font-semibold">
                {formatLatency(flowData.summary.avg_latency_ms)}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 flex-col items-center justify-center gap-2 text-xs text-gray-500"
        >
          <svg className="h-8 w-8 text-nexus-border" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="5" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="19" cy="12" r="2" />
            <path d="M7 12h3M14 12h3" />
          </svg>
          <div>Sem dados de fluxo</div>
          <div className="text-gray-600">Inicia o backend para ver o fluxo</div>
        </motion.div>
      )}
    </motion.div>
  );
}
