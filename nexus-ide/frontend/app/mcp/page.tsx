"use client";

import { motion } from "framer-motion";
import AppShell from "../../components/layout/AppShell";
import MCPWizard from "../../components/mcp/MCPWizard";

export default function MCPPage() {
  return (
    <AppShell title="MCP Control Center">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <MCPWizard />
      </motion.div>
    </AppShell>
  );
}
