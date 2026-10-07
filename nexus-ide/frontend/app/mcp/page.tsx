"use client";

import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import MCPBuilderPanel from "../../components/mcp/MCPBuilderPanel";
import MCPWizard from "../../components/mcp/MCPWizard";

export default function MCPPage() {
  return (
    <AppShell title="MCP Control Center">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <MCPBuilderPanel />
        <MCPWizard />
      </motion.div>
    </AppShell>
  );
}
