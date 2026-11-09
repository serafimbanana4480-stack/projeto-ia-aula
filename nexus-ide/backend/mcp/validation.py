"""Contract validation for MCP tools, schemas, arguments, and connector roots.

The MCP protocol lets a server advertise any tool name and any
``inputSchema``. NEXUS forwards model-supplied arguments straight to the
server, so a malformed contract (a name that is not an identifier, a schema
that is not a JSON-Schema object) and a path that escapes the connector's
declared root have to be rejected here — before the call leaves the process.

This module is deliberately dependency-free: it is imported by the runtime
hot path and must not add an install-time requirement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: MCP tool names are identifiers, not free text: letters, digits, ``_``, ``-``
#: and ``.``. Anything else cannot be addressed safely.
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

#: Argument names that are treated as filesystem paths when a connector
#: declares a root (the filesystem template, Serena, ProjectMind, ...).
_PATH_ARGUMENT_HINTS = ("path", "file", "dir", "folder", "root", "cwd")

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def is_valid_tool_name(name: Any) -> bool:
    """Return whether *name* is a usable MCP tool identifier."""
    return isinstance(name, str) and bool(_TOOL_NAME_PATTERN.fullmatch(name))


def is_valid_input_schema(schema: Any) -> bool:
    """Return whether *schema* is a JSON Schema object NEXUS can validate.

    A usable MCP input schema is a JSON Schema ``object``: it declares
    ``"type": "object"`` and, when it declares ``properties``, those are
    objects. A schema that declares structure without a ``type`` cannot be
    enforced, so the tool advertising it is refused instead of being called
    blindly.

    An *empty* schema (``{}``) declares no constraints at all: it is a valid
    JSON Schema and is accepted, because some servers (and NEXUS' own MCP
    test doubles) advertise it.
    """
    if not isinstance(schema, dict):
        return False
    if not schema:
        return True
    if schema.get("type") != "object":
        return False
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return False
    if not all(isinstance(item, dict) for item in properties.values()):
        return False
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list):
            return False
        if any(not isinstance(name, str) for name in required):
            return False
    return True


def _type_matches(value: Any, expected: str) -> bool:
    types = _JSON_TYPES.get(expected)
    if types is None:
        return True
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, types)


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    """Validate one value against the subset of JSON Schema NEXUS enforces."""
    errors: list[str] = []
    expected = schema.get("type")
    if isinstance(expected, str) and expected in _JSON_TYPES and not _type_matches(value, expected):
        errors.append(f"'{path}' devia ser do tipo {expected}")
        return errors
    if "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
        errors.append(f"'{path}' não é um valor permitido")
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"'{path}' é mais curto que {minimum_length} caracteres")
        maximum_length = schema.get("maxLength")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            errors.append(f"'{path}' excede {maximum_length} caracteres")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    errors.append(f"'{path}' não corresponde ao formato exigido")
            except re.error:  # pragma: no cover - invalid server-side pattern
                pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"'{path}' é menor que {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"'{path}' é maior que {maximum}")
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_value(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, dict):
        errors.extend(_validate_object(value, schema, path))
    return errors


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in value:
                errors.append(f"'{path}' não tem o campo obrigatório '{name}'")
    additional = schema.get("additionalProperties", True)
    for name, item in value.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            errors.extend(_validate_value(item, property_schema, f"{path}.{name}"))
        elif additional is False:
            errors.append(f"'{path}' tem o campo não permitido '{name}'")
    return errors


def validate_arguments(schema: Any, arguments: Any) -> list[str]:
    """Return the schema violations of *arguments* (empty list when valid)."""
    if not is_valid_input_schema(schema):
        return ["inputSchema inválido"]
    if not isinstance(arguments, dict):
        return ["os argumentos têm de ser um objeto"]
    return _validate_object(arguments, schema, "arguments")


def _looks_like_path(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _PATH_ARGUMENT_HINTS)


def root_boundary_violations(
    root: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> list[str]:
    """Return the arguments that escape the connector's declared *root*.

    A connector built from the filesystem template (or Serena, or
    ProjectMind) is scoped to one directory. Relative paths are resolved
    against that root — the MCP child process is started there — and
    absolute paths must already be inside it.
    """
    if not root or not isinstance(arguments, dict):
        return []
    try:
        base = Path(root).resolve()
    except OSError:  # pragma: no cover - unreadable root
        return []
    violations: list[str] = []
    for name, value in arguments.items():
        if not isinstance(value, str) or not value.strip():
            continue
        if not _looks_like_path(name):
            continue
        try:
            candidate = Path(value)
            target = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
        except (OSError, ValueError):  # pragma: no cover - malformed path
            violations.append(f"'{name}' não é um caminho válido")
            continue
        if target != base and base not in target.parents:
            violations.append(f"'{name}' está fora da raiz permitida do connector")
    return violations
