"use client";
import { motion } from "framer-motion";
import TopBar from "../../../../components/layout/TopBar";
import Sidebar from "../../../../components/layout/Sidebar";
import BottomHUD from "../../../../components/layout/BottomHUD";
import { Network } from "lucide-react";

export default function MemoryGraphPage() {
  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="mb-6 flex items-center gap-3">
              <Network className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">Knowledge Graph</h1>
            </div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="rounded border border-nexus-border bg-nexus-panel/50 p-6"
            >
              <h2 className="text-lg font-semibold mb-4">Knowledge Graph System</h2>
              <p className="text-gray-400 mb-4">
                Knowledge graph stores relationships between entities, files, agents, and decisions.
              </p>
              
              <div className="bg-black/30 rounded-lg p-8 flex items-center justify-center min-h-64">
                <p className="text-gray-500">
                  Interactive graph visualization is available in the main dashboard.
                  Navigate to the dashboard to see the Knowledge Graph preview.
                </p>
              </div>
            </motion.div>
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
