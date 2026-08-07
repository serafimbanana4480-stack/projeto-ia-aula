"use client";
import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import { Plug } from "lucide-react";
import MCPWizard from "../../components/mcp/MCPWizard";

export default function MCPPage() {
  return (
    <AppShell title="Conectores MCP">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <div className="mb-6 flex items-center gap-3">
          <Plug className="h-6 w-6 text-nexus-text" />
          <div>
            <h1 className="text-2xl font-bold">Conectores MCP</h1>
            <p className="text-sm text-nexus-muted">
              Liga o NEXUS a servidores MCP (Model Context Protocol) — filesystem, GitHub, bases de dados,
              pesquisa web e mais — sem editar JSON à mão.
            </p>
          </div>
        </div>

        <MCPWizard />
      </motion.div>
    </AppShell>
  );
}
