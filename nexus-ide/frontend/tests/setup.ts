import { vi } from "vitest";

// Node 26 adds a global `localStorage` accessor that is undefined unless
// `--localstorage-file` is supplied. It shadows JSDOM storage in Vitest, so
// provide a fresh in-memory browser-compatible store for each test file.
const storageValues = new Map<string, string>();
const testLocalStorage = {
  get length() {
    return storageValues.size;
  },
  clear: () => storageValues.clear(),
  getItem: (key: string) => storageValues.get(String(key)) ?? null,
  key: (index: number) => Array.from(storageValues.keys())[index] ?? null,
  removeItem: (key: string) => {
    storageValues.delete(String(key));
  },
  setItem: (key: string, value: string) => {
    storageValues.set(String(key), String(value));
  },
} as Storage;
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  writable: true,
  value: testLocalStorage,
});

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
