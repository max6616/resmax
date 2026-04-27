from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationError:
    path: str
    message: str

    def format(self) -> str:
        return f"{self.path}: {self.message}"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_instance(instance: Any, schema: dict[str, Any], path: str = "$") -> list[ValidationError]:
    errors: list[ValidationError] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(matches_type(instance, t) for t in expected_type):
            errors.append(ValidationError(path, f"expected one of {expected_type}, got {type_name(instance)}"))
            return errors
    elif isinstance(expected_type, str):
        if not matches_type(instance, expected_type):
            errors.append(ValidationError(path, f"expected {expected_type}, got {type_name(instance)}"))
            return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(ValidationError(path, f"expected constant {schema['const']!r}"))

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(ValidationError(path, f"expected one of {schema['enum']!r}, got {instance!r}"))

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(ValidationError(path, f"expected minLength {min_length}"))
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.search(pattern, instance):
            errors.append(ValidationError(path, f"does not match pattern {pattern!r}"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and instance < minimum:
            errors.append(ValidationError(path, f"expected minimum {minimum}"))
        if maximum is not None and instance > maximum:
            errors.append(ValidationError(path, f"expected maximum {maximum}"))

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(instance) < min_items:
            errors.append(ValidationError(path, f"expected at least {min_items} item(s)"))
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(instance) > max_items:
            errors.append(ValidationError(path, f"expected at most {max_items} item(s)"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                errors.extend(validate_instance(item, item_schema, f"{path}[{idx}]"))

    if isinstance(instance, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in instance:
                    errors.append(ValidationError(f"{path}.{key}", "required field missing"))

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, prop_schema in properties.items():
                if key in instance and isinstance(prop_schema, dict):
                    errors.extend(validate_instance(instance[key], prop_schema, f"{path}.{key}"))

        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            allowed = set(properties)
            for key in instance:
                if key not in allowed:
                    errors.append(ValidationError(f"{path}.{key}", "additional field is not allowed"))

    return errors


def _has_reference(obj: dict[str, Any]) -> bool:
    reference_fields = (
        "evidence_card_id",
        "evidence_card_ids",
        "evidence_span_id",
        "evidence_span_ids",
    )
    for field in reference_fields:
        value = obj.get(field)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value):
            return True
    return False


def validate_strong_claims(value: Any, path: str = "$") -> list[ValidationError]:
    errors: list[ValidationError] = []
    if isinstance(value, dict):
        strength = value.get("claim_strength", value.get("strength"))
        if strength == "strong" and value.get("evidence_status") != "insufficient_evidence":
            if not _has_reference(value):
                errors.append(
                    ValidationError(
                        path,
                        "strong claim must reference evidence_card_id/evidence_span_id or use evidence_status='insufficient_evidence'",
                    )
                )
        for key, child in value.items():
            errors.extend(validate_strong_claims(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(validate_strong_claims(child, f"{path}[{idx}]"))
    return errors


def validate_with_schema(instance: Any, schema: dict[str, Any]) -> list[ValidationError]:
    return validate_instance(instance, schema) + validate_strong_claims(instance)


def print_errors(errors: list[ValidationError], *, prefix: str = "ERROR") -> None:
    for error in errors:
        print(f"{prefix} {error.format()}")


def validate_json_file(input_path: Path, schema_path: Path) -> list[ValidationError]:
    instance = load_json(input_path)
    schema = load_json(schema_path)
    return validate_with_schema(instance, schema)
