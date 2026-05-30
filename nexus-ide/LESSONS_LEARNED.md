# LESSONS LEARNED — NEXUS IDE Recovery

**Date:** 2026-05-29

---

## 1. Test-First Saves Time

The project had 460+ tests. Running them immediately revealed 10 real bugs that would have broken production. Without tests, these would only surface during user interaction.

**Lesson:** Always run the full test suite first. It's the fastest way to find regressions.

---

## 2. Constructor Refactors Must Propagate to Tests

The `OrchestrationEngine` constructor was refactored from `ollama=` to `llm_client=` but 2 test files were not updated. This caused 9 test errors immediately.

**Lesson:** When refactoring public APIs, use grep to find all call sites — including tests.

---

## 3. Cross-Platform Path Handling Is Easy to Get Wrong

String matching on `/` fails on Windows. The project analyzer's test detection used `/test` and `test/` but Windows paths use `\`.

**Lesson:** Always normalize paths with `.replace("\\", "/")` or use `Path.as_posix()` before string comparison.

---

## 4. Frontend SVG Icons Can Block Clicks

The send button in the chat UI used an SVG icon without `pointer-events-none`. On some browsers, clicking the icon itself didn't trigger the button's click handler.

**Lesson:** Always add `pointer-events-none` to icons inside clickable buttons.

---

## 5. pyproject.toml Needs Explicit Package Declaration

Setuptools' auto-discovery failed because the repo root had multiple directories (`backend`, `frontend`, `config`, etc.).

**Lesson:** Always declare `[tool.setuptools] packages` explicitly in monorepos.

---

## 6. ReAct Loop Changes Break Token-Exact Tests

When the agent base class started emitting `<event>` markers, tests that asserted exact token arrays broke.

**Lesson:** Test streaming outputs with `in` or pattern matching rather than exact array equality.

---

## 7. Integration Tests Need Real Services

The chat endpoint streams via SSE. Testing it with `curl` confirmed the full backend→network→client path works, something unit tests cannot verify.

**Lesson:** Always do at least one manual end-to-end call to the main endpoint.

---

## 8. Parallel Agents Accelerate Audits

Using multiple explore agents in parallel allowed mapping the backend, frontend, and configuration simultaneously.

**Lesson:** Split large exploration tasks into parallel agents for speed.

---

## 9. Test Pollution Is Real

Two tests passed in isolation but failed in the full suite. This indicates shared mutable state (likely SQLite or filesystem).

**Lesson:** Use `pytest-randomly` to surface order-dependent bugs early.

---

## 10. Documentation Drives Understanding

The project had excellent docs: ARCHITECTURE.md, README.md, planeamento/ docs. This made understanding the system fast.

**Lesson:** Good documentation is as important as good code for maintainability.
