"use client";
import { motion } from "framer-motion";
import TopBar from "../../../components/layout/TopBar";
import Sidebar from "../../../components/layout/Sidebar";
import BottomHUD from "../../../components/layout/BottomHUD";
import { Settings } from "lucide-react";

export default function SettingsPage() {
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
              <Settings className="h-6 w-6 text-nexus-text" />
              <h1 className="text-2xl font-bold">Settings</h1>
            </div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="rounded border border-nexus-border bg-nexus-panel/50 p-6"
            >
              <h2 className="text-lg font-semibold mb-4">System Configuration</h2>
              <p className="text-gray-400 mb-4">
                Configure agent behavior, model selection, security settings, and system preferences.
              </p>
              
              <div className="bg-black/30 rounded-lg p-8 flex items-center justify-center min-h-64">
                <p className="text-gray-500">
                  Settings interface is under development.
                  Full configuration options will be available soon.
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
