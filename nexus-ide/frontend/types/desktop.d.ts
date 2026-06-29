export interface DesktopBridge {
  selectDirectory: () => Promise<string | null>;
  listFiles: (
    root: string,
    target?: string,
    recursive?: boolean,
  ) => Promise<{
    path: string;
    count: number;
    items: Array<{
      path: string;
      name: string;
      type: "file" | "directory";
      size: number;
      children?: unknown[];
    }>;
  }>;
  readFile: (
    root: string,
    target: string,
  ) => Promise<{ path: string; content: string; size: number }>;
  writeFile: (
    root: string,
    target: string,
    content: string,
  ) => Promise<{ path: string; written: boolean; size: number }>;
  executeCommand: (
    root: string,
    command: string,
    timeoutSeconds?: number,
  ) => Promise<{
    execution_id: string;
    command: string;
    stdout: string;
    stderr: string;
    exit_code: number;
    timed_out: boolean;
    duration_ms: number;
    risk_level: string;
  }>;
}

declare global {
  interface Window {
    nexusDesktop?: DesktopBridge;
  }
}

export {};
