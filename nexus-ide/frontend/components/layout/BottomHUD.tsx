"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Cpu, HardDrive, Clock, LogOut, X } from "lucide-react";

export default function BottomHUD() {
  const [showLogs, setShowLogs] = useState(false);

  return (
    <>
      <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="flex items-center justify-between border-t border-nexus-border bg-nexus-panel/50 px-4 py-2 backdrop-blur-md text-xs"
    >
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-gray-400">System</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-gray-400">Ollama</span>
        </div>
        <div className="flex items-center gap-2 text-gray-400">
          <Cpu className="h-3 w-3" />
          <span>CPU</span>
          <span className="text-nexus-accent">📈</span>
        </div>
        <div className="flex items-center gap-2 text-gray-400">
          <HardDrive className="h-3 w-3" />
          <span>RAM</span>
          <span className="text-nexus-accent">📈</span>
        </div>
        <div className="flex items-center gap-2 text-gray-400">
          <Activity className="h-3 w-3" />
          <span>GPU</span>
          <span className="text-nexus-accent">📈</span>
        </div>
      </div>

      <div className="flex items-center gap-4 text-gray-400">
        <div className="flex items-center gap-2">
          <Clock className="h-3 w-3" />
          <span>Uptime: 2h 34m</span>
        </div>
        <div className="h-4 w-px bg-nexus-border" />
        <button 
          onClick={() => setShowLogs(true)}
          className="flex items-center gap-2 hover:text-gray-300"
        >
          <LogOut className="h-3 w-3" />
          <span>Logs</span>
        </button>
      </div>
    </motion.div>

    <AnimatePresence>
      {showLogs && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowLogs(false)}
        >
          <motion.div
            initial={{ scale: 0.95 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0.95 }}
            className="h-96 w-full max-w-4xl overflow-auto rounded border border-nexus-border bg-nexus-panel p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">System Logs</h2>
              <button
                onClick={() => setShowLogs(false)}
                className="rounded hover:bg-nexus-border p-1"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-2 text-xs font-mono">
              <div className="rounded bg-black/30 p-2">
                <div className="text-green-400">✓ Ollama running on port 11434</div>
                <div className="text-green-400">✓ Backend running on port 8000</div>
                <div className="text-green-400">✓ Frontend running on port 3000</div>
              </div>
              <div className="rounded bg-black/30 p-2 text-gray-400">
                <div>Logs are available in the logs/ directory</div>
                <div>• logs/ollama.log</div>
                <div>• logs/backend.log</div>
                <div>• logs/frontend.log</div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
    </>
  );
}
