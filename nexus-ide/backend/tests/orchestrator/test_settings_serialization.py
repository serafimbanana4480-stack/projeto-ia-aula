"""Regression tests for the runtime settings API."""

from __future__ import annotations

import json

from backend.orchestrator.routes.settings import _get_public_settings


def test_public_settings_are_json_serializable_and_secrets_are_masked() -> None:
    public = _get_public_settings()

    # This raised PydanticSerializationError when the endpoint iterated
    # dir(Settings) and included model_fields / FieldInfo metadata.
    json.dumps(public)

    assert "model_fields" not in public
    for key, value in public.items():
        if key.endswith(("api_key", "secret", "password", "token")) and value:
            assert value == "********" or "****" in str(value)
