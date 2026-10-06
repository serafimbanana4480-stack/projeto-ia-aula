import { describe, expect, it } from "vitest";
import type { Tool } from "../../lib/types";
import { toolAvailability, toolGroup, toolParameters } from "../../lib/toolCatalog";

const tool: Tool = { name: "todo_list", description: "Read tasks", enabled: true, requires_confirmation: false, schema: {} };
describe("runtime tool catalog metadata", () => {
  it("prioritises missing dependencies over enabled state", () => {
    expect(toolAvailability({ ...tool, status: "missing_dependency", missing_dependency: "library" }).id).toBe("unavailable");
    expect(toolAvailability({ ...tool, available: false }).id).toBe("unavailable");
    expect(toolAvailability({ ...tool, enabled: false, requires_confirmation: true }).id).toBe("disabled");
    expect(toolAvailability({ ...tool, requires_confirmation: true }).id).toBe("confirmation");
  });
  it("groups tools by the workflow users need", () => {
    expect(toolGroup(tool)).toBe("planning");
    expect(toolGroup({ name: "load_skill" })).toBe("skills");
    expect(toolGroup({ name: "spawn_task" })).toBe("agents");
    expect(toolGroup({ name: "read_file" })).toBe("code");
  });
  it("retains parameter types and required fields from the real schema", () => {
    expect(toolParameters({ properties: { path: { type: "string", description: "Project path" }, limit: { type: "number" } }, required: ["path"] })).toEqual([
      { name: "path", type: "string", required: true, description: "Project path" },
      { name: "limit", type: "number", required: false, description: "" },
    ]);
  });
});
