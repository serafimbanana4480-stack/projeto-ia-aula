import type { FileTreeEntry, TerminalExecutionResult } from "./types";

function buildTree(entries: FileTreeEntry[]): FileTreeEntry[] {
  const nodes = new Map<string, FileTreeEntry>();
  const roots: FileTreeEntry[] = [];

  for (const entry of entries) {
    nodes.set(entry.path, { ...entry, children: [] });
  }

  for (const entry of entries) {
    const node = nodes.get(entry.path)!;
    const parentPath = entry.path.includes("/")
      ? entry.path.split("/").slice(0, -1).join("/")
      : "";
    if (!parentPath) {
      roots.push(node);
      continue;
    }
    const parent = nodes.get(parentPath);
    if (parent) {
      parent.children = parent.children ?? [];
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

function hasDesktopBridge(): boolean {
  return (
    typeof window !== "undefined" && typeof window.nexusDesktop !== "undefined"
  );
}

export async function selectDesktopDirectory(): Promise<string | null> {
  if (!hasDesktopBridge()) return null;
  return window.nexusDesktop!.selectDirectory();
}

export async function desktopListFiles(
  root: string,
  path = ".",
  recursive = true,
): Promise<FileTreeEntry[]> {
  if (!hasDesktopBridge()) return [];
  const result = await window.nexusDesktop!.listFiles(root, path, recursive);
  return buildTree(result.items as FileTreeEntry[]);
}

export async function desktopReadFile(
  root: string,
  path: string,
): Promise<{ content: string }> {
  if (!hasDesktopBridge()) return { content: "" };
  const result = await window.nexusDesktop!.readFile(root, path);
  return { content: result.content };
}

export async function desktopWriteFile(
  root: string,
  path: string,
  content: string,
): Promise<void> {
  if (!hasDesktopBridge()) return;
  await window.nexusDesktop!.writeFile(root, path, content);
}

export async function desktopExecuteCommand(
  root: string,
  command: string,
  timeoutSeconds = 30,
): Promise<TerminalExecutionResult | null> {
  if (!hasDesktopBridge()) return null;
  return window.nexusDesktop!.executeCommand(root, command, timeoutSeconds);
}
