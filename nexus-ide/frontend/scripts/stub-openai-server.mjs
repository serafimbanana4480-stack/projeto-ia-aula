/**
 * NEXUS audit stub — a real OpenAI-compatible HTTP server.
 *
 * It exists because this machine has no usable LLM credential (the
 * opencode_go key is a placeholder and OpenRouter's quota is exhausted), so
 * the live chat path could not otherwise be exercised at all.
 *
 * It speaks the *real* wire protocol the product uses:
 *   GET  /v1/models
 *   POST /v1/chat/completions   (SSE: reasoning_content, content, tool_calls, usage)
 *
 * The scenario is read from ./stub-scenario.json (or $NEXUS_STUB_SCENARIO) and
 * is re-read on every request, so a test can change the script between turns.
 * Each request consumes the next step of the step list.
 *
 * This is a TEST DOUBLE, not a model. It is only ever used to verify the
 * transport, the event contract and the UI rendering.
 */
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const PORT = Number(process.env.NEXUS_STUB_PORT ?? 1234);
const SCENARIO =
  process.env.NEXUS_STUB_SCENARIO ?? join(import.meta.dirname, "stub-scenario.json");

let counter = 0;

function loadScenario() {
  if (!existsSync(SCENARIO)) return { steps: [] };
  try {
    return JSON.parse(readFileSync(SCENARIO, "utf8"));
  } catch (e) {
    return { steps: [], error: String(e) };
  }
}

function sse(res, obj) {
  res.write(`data: ${JSON.stringify(obj)}\n\n`);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (req.method === "GET" && url.pathname.endsWith("/models")) {
    const scenario = loadScenario();
    const models = scenario.models ?? [
      { id: "nexus-stub-coder", object: "model", owned_by: "nexus-audit-stub" },
    ];
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ object: "list", data: models }));
    return;
  }

  if (req.method === "POST" && url.pathname.endsWith("/chat/completions")) {
    let body = "";
    for await (const chunk of req) body += chunk;
    let payload = {};
    try {
      payload = JSON.parse(body || "{}");
    } catch {
      /* ignore */
    }

    const scenario = loadScenario();
    const steps = scenario.steps ?? [];
    const modes = scenario.modes ?? {};

    // Pick the step the way a real model would: if the caller offered tools
    // and the conversation does not yet contain a tool result, ask for a tool;
    // once a tool result is present, answer with the follow-up text.
    const hasTools = Array.isArray(payload.tools) && payload.tools.length > 0;
    const sawToolResult = (payload.messages ?? []).some(
      (m) => m && (m.role === "tool" || m.tool_call_id),
    );
    let step;
    if (hasTools && !sawToolResult) {
      step = modes.tool ?? steps[0] ?? {};
    } else if (hasTools && sawToolResult) {
      step = modes.after_tool ?? steps[steps.length - 1] ?? {};
    } else {
      step = modes.text ?? steps[0] ?? {};
    }

    // A step can be an error, or a list of frames to emit.
    if (step.error) {
      res.writeHead(step.status ?? 500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { message: step.error, type: "server_error" } }));
      return;
    }

    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    });

    const delay = Number(step.delayMs ?? 25);
    for (const frame of step.frames ?? []) {
      if (frame.reasoning) {
        sse(res, {
          id: "cmpl-stub",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: payload.model ?? "nexus-stub",
          choices: [
            { index: 0, delta: { reasoning_content: frame.reasoning }, finish_reason: null },
          ],
        });
      }
      if (frame.content !== undefined) {
        sse(res, {
          id: "cmpl-stub",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: payload.model ?? "nexus-stub",
          choices: [{ index: 0, delta: { content: frame.content }, finish_reason: null }],
        });
      }
      if (frame.tool_call) {
        sse(res, {
          id: "cmpl-stub",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: payload.model ?? "nexus-stub",
          choices: [
            {
              index: 0,
              delta: {
                tool_calls: [
                  {
                    index: 0,
                    id: frame.tool_call.id ?? "call_stub_1",
                    type: "function",
                    function: {
                      name: frame.tool_call.name,
                      arguments: JSON.stringify(frame.tool_call.arguments ?? {}),
                    },
                  },
                ],
              },
              finish_reason: null,
            },
          ],
        });
      }
      if (frame.finish_reason) {
        sse(res, {
          id: "cmpl-stub",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: payload.model ?? "nexus-stub",
          choices: [{ index: 0, delta: {}, finish_reason: frame.finish_reason }],
        });
      }
      await new Promise((r) => setTimeout(r, delay));
    }

    if (step.usage !== false) {
      sse(res, {
        id: "cmpl-stub",
        object: "chat.completion.chunk",
        created: Math.floor(Date.now() / 1000),
        model: payload.model ?? "nexus-stub",
        choices: [],
        usage: {
          prompt_tokens: step.usage?.prompt_tokens ?? 120,
          completion_tokens: step.usage?.completion_tokens ?? 80,
          total_tokens:
            (step.usage?.prompt_tokens ?? 120) + (step.usage?.completion_tokens ?? 80),
          completion_tokens_details: {
            reasoning_tokens: step.usage?.reasoning_tokens ?? 24,
          },
        },
      });
    }
    res.write("data: [DONE]\n\n");
    res.end();
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "not found" }));
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[stub] OpenAI-compatible stub on http://127.0.0.1:${PORT} (scenario: ${SCENARIO})`);
});
