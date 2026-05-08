"use client";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { FileText } from "lucide-react";

export default function DocumentsPage() {
  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex h-full items-center justify-center"
          >
            <div className="text-center">
              <FileText className="mx-auto mb-4 h-16 w-16 text-nexus-accent" />
              <h1 className="mb-2 text-2xl font-bold">Documents</h1>
              <p className="text-gray-400">Coming Soon</p>
              <p className="mt-2 text-sm text-gray-500">Browse and manage project documents</p>
            </div>
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
