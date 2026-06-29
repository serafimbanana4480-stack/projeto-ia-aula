"use client";

import EditorWorkspace from "../../components/editor/EditorWorkspace";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";

export default function EditorPage() {
  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-hidden">
          <EditorWorkspace />
        </main>
      </div>
      <BottomHUD />
    </div>
  );
}
