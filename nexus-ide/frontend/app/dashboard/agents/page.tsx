"use client";
import { motion } from "framer-motion";
import TopBar from "../../../components/layout/TopBar";
import Sidebar from "../../../components/layout/Sidebar";
import BottomHUD from "../../../components/layout/BottomHUD";
import { Activity, Users } from "lucide-react";

export default function AgentsPage() {
  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="max-w-6xl mx-auto"
          >
            <div className="mb-6 flex items-center gap-3">
              <Activity className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">Agents</h1>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="flex items-center gap-2 mb-3">
                  <Users className="h-5 w-5 text-nexus-accent" />
                  <h3 className="font-semibold">All Agents</h3>
                </div>
                <p className="text-sm text-gray-400">
                  View and manage all AI agents in the system
                </p>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="flex items-center gap-2 mb-3">
                  <Activity className="h-5 w-5 text-cyan-400" />
                  <h3 className="font-semibold">Agent Topology</h3>
                </div>
                <p className="text-sm text-gray-400">
                  Visualize agent network and communication
                </p>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
              >
                <div className="flex items-center gap-2 mb-3">
                  <Activity className="h-5 w-5 text-amber-400" />
                  <h3 className="font-semibold">Performance</h3>
                </div>
                <p className="text-sm text-gray-400">
                  Monitor agent performance and metrics
                </p>
              </motion.div>
            </div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mt-8 rounded border border-nexus-border bg-nexus-panel/50 p-6"
            >
              <h2 className="text-lg font-semibold mb-4">Active Agents</h2>
              <p className="text-gray-400">
                Detailed agent management is available in the main dashboard.
                Navigate to the dashboard to see the complete agent topology and real-time status.
              </p>
            </motion.div>
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
