import { describe, expect, it, vi, afterEach } from "vitest";
import {
  selectDesktopDirectory,
  desktopListFiles,
  desktopReadFile,
  desktopWriteFile,
  desktopExecuteCommand,
} from "../../lib/desktop";

describe("lib/desktop", () => {
  describe("hasDesktopBridge (indirect via wrappers)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("selectDesktopDirectory returns null when bridge is absent", async () => {
      vi.stubGlobal("window", {});
      const result = await selectDesktopDirectory();
      expect(result).toBeNull();
    });

    it("desktopListFiles returns empty array when bridge is absent", async () => {
      vi.stubGlobal("window", {});
      const result = await desktopListFiles("/root");
      expect(result).toEqual([]);
    });

    it("desktopReadFile returns empty content when bridge is absent", async () => {
      vi.stubGlobal("window", {});
      const result = await desktopReadFile("/root", "file.txt");
      expect(result).toEqual({ content: "" });
    });

    it("desktopWriteFile returns void when bridge is absent", async () => {
      vi.stubGlobal("window", {});
      const result = await desktopWriteFile("/root", "file.txt", "content");
      expect(result).toBeUndefined();
    });

    it("desktopExecuteCommand returns null when bridge is absent", async () => {
      vi.stubGlobal("window", {});
      const result = await desktopExecuteCommand("/root", "ls");
      expect(result).toBeNull();
    });
  });

  describe("with mock bridge", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("selectDesktopDirectory calls bridge.selectDirectory", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          selectDirectory: vi.fn().mockResolvedValue("/selected/path"),
        },
      });
      const result = await selectDesktopDirectory();
      expect(result).toBe("/selected/path");
      expect(window.nexusDesktop!.selectDirectory).toHaveBeenCalledTimes(1);
    });

    it("desktopListFiles builds tree from bridge result", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          listFiles: vi.fn().mockResolvedValue({
            path: "/",
            count: 2,
            items: [
              { path: "file1", name: "file1", type: "file", size: 100 },
              { path: "dir1", name: "dir1", type: "directory", size: 0 },
            ],
          }),
        },
      });
      const result = await desktopListFiles("/root");
      expect(window.nexusDesktop!.listFiles).toHaveBeenCalledWith("/root", ".", true);
      expect(result).toHaveLength(2);
      expect(result[0].path).toBe("file1");
      expect(result[0].children).toEqual([]);
    });

    it("desktopListFiles passes recursive=false", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          listFiles: vi.fn().mockResolvedValue({ path: "/", count: 0, items: [] }),
        },
      });
      await desktopListFiles("/root", ".", false);
      expect(window.nexusDesktop!.listFiles).toHaveBeenCalledWith("/root", ".", false);
    });

    it("desktopListFiles builds nested tree", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          listFiles: vi.fn().mockResolvedValue({
            path: "/",
            count: 4,
            items: [
              { path: "src", name: "src", type: "directory", size: 0 },
              { path: "src/utils", name: "utils", type: "directory", size: 0 },
              { path: "src/utils/helper.py", name: "helper.py", type: "file", size: 500 },
              { path: "src/utils/__init__.py", name: "__init__.py", type: "file", size: 0 },
            ],
          }),
        },
      });
      const result = await desktopListFiles("/root");
      expect(result).toHaveLength(1); // only "src" at root
      expect(result[0].path).toBe("src");
      expect(result[0].children).toHaveLength(1);
      expect(result[0].children![0].path).toBe("src/utils");
      expect(result[0].children![0].children).toHaveLength(2);
    });

    it("desktopListFiles handles empty items", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          listFiles: vi.fn().mockResolvedValue({ path: "/", count: 0, items: [] }),
        },
      });
      const result = await desktopListFiles("/root");
      expect(result).toEqual([]);
    });

    it("desktopReadFile calls bridge.readFile and returns content", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          readFile: vi.fn().mockResolvedValue({ path: "file1", content: "hello", size: 5 }),
        },
      });
      const result = await desktopReadFile("/root", "file.txt");
      expect(window.nexusDesktop!.readFile).toHaveBeenCalledWith("/root", "file.txt");
      expect(result).toEqual({ content: "hello" });
    });

    it("desktopWriteFile calls bridge.writeFile", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          writeFile: vi.fn().mockResolvedValue({ path: "file1", written: true, size: 5 }),
        },
      });
      await desktopWriteFile("/root", "file.txt", "content");
      expect(window.nexusDesktop!.writeFile).toHaveBeenCalledWith("/root", "file.txt", "content");
    });

    it("desktopExecuteCommand calls bridge.executeCommand with timeout", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          executeCommand: vi.fn().mockResolvedValue({
            execution_id: "exec-1",
            command: "ls",
            stdout: "output",
            stderr: "",
            exit_code: 0,
            timed_out: false,
            duration_ms: 50,
            risk_level: "safe",
          }),
        },
      });
      const result = await desktopExecuteCommand("/root", "ls", 60);
      expect(window.nexusDesktop!.executeCommand).toHaveBeenCalledWith("/root", "ls", 60);
      expect(result).toMatchObject({
        execution_id: "exec-1",
        stdout: "output",
        exit_code: 0,
      });
    });

    it("desktopExecuteCommand uses default timeout when not provided", async () => {
      vi.stubGlobal("window", {
        nexusDesktop: {
          executeCommand: vi.fn().mockResolvedValue({
            execution_id: "exec-1",
            command: "ls",
            stdout: "output",
            stderr: "",
            exit_code: 0,
            timed_out: false,
            duration_ms: 50,
            risk_level: "safe",
          }),
        },
      });
      await desktopExecuteCommand("/root", "ls");
      expect(window.nexusDesktop!.executeCommand).toHaveBeenCalledWith("/root", "ls", 30);
    });
  });
});
