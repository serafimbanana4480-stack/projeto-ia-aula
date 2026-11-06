import { describe, expect, it } from "vitest";
import { mergeChildFrames } from "../../../components/chat/AgentTranscript";

describe("mergeChildFrames", () => {
  it("dedupes by seq (local wins) and sorts", () => {
    const local = [{ type: "progress", seq: 2, data: { v: "local" } }] as never[];
    const durable = [
      { type: "progress", data: { seq: 3, v: "d3" } },
      { type: "progress", data: { seq: 2, v: "d2" } },
      { type: "progress", data: { seq: 1, v: "d1" } },
    ] as never[];
    const merged = mergeChildFrames(local, durable) as unknown as Array<{ data: { v: string } }>;
    expect(merged.map((f) => f.data.v)).toEqual(["d1", "local", "d3"]);
  });
});
