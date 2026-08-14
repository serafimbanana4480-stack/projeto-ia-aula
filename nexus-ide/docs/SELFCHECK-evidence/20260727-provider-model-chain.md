# NEXUS provider/model self-check — 2026-07-27

All identifiers below came from the local UI/backend run. Credentials, headers and prompt bodies are intentionally omitted.

## Red test: UI selection without provider in `/api/chat`

- UI selection: `deepseek-v4-flash`; side panel displayed provider `opencode_go`.
- Frontend request builder before the fix included `model`, but not `provider`.
- Backend route event: `requested_provider=""`, `effective_provider="openrouter"`.
- SDK event: `provider="openrouter"`, `model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"`.
- Result: the UI's concrete model/provider display was not proof of execution. The selected id was remapped by OpenRouter and the provider changed silently.

## Green test: provider is transported and cannot be silently substituted

The UI now carries both concrete values in the request body:

```json
{"model":"cohere/north-mini-code:free","provider":"openrouter"}
```

Observed route and SDK events for session `audit_openrouter_green_20260727`:

```json
{"event":"chat_provider_resolved","requested_provider":"openrouter","effective_provider":"openrouter","client":"OpenRouterProvider","model":"cohere/north-mini-code:free"}
{"event":"llm_dispatch_resolved","provider":"openrouter","model":"cohere/north-mini-code:free"}
{"event":"llm_sdk_dispatch","provider":"openrouter","model":"cohere/north-mini-code:free"}
```

This is the accepted proof chain: concrete UI id → JSON payload → route provider/client → provider-resolved model → SDK model. For `opencode_go`, the green negative test returns an SSE error saying the provider is not configured/active; it does not fall back to OpenRouter.

