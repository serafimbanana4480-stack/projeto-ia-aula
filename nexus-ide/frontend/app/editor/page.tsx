"use client";

import EditorWorkspace from "../../components/editor/EditorWorkspace";
import AppShell from "../../components/layout/AppShell";

export default function EditorPage() {
  return (
    <AppShell title="Editor" noPadding>
      <EditorWorkspace />
    </AppShell>
  );
}
