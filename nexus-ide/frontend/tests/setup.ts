import { vi } from "vitest";

// Mock Monaco Editor for headless tests
vi.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: () => null,
}));

// Mock xterm for headless tests
vi.mock("xterm", () => ({
  Terminal: class {
    open() {}
    write() {}
    onData() {}
    dispose() {}
  },
}));
