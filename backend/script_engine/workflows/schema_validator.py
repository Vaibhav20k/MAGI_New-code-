import json
from pathlib import Path
from typing import Dict, Any, Tuple
import jsonschema

class SchemaValidationError(Exception):
    """Custom exception raised when data fails schema validation."""
    pass

class SchemaValidator:
    """Validates engine artifacts against strict JSON schemas."""

    def __init__(self, schemas_dir: Path):
        self.schemas_dir = schemas_dir
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_schema(self, schema_filename: str) -> Dict[str, Any]:
        if schema_filename not in self._cache:
            schema_path = self.schemas_dir / schema_filename
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            with open(schema_path, "r", encoding="utf-8") as f:
                self._cache[schema_filename] = json.load(f)
        return self._cache[schema_filename]

    def validate(self, data: Dict[str, Any], schema_filename: str) -> Tuple[bool, str]:
        """
        Validates data against the specified schema file.
        Returns (is_valid, error_message).
        """
        schema = self._get_schema(schema_filename)
        try:
            jsonschema.validate(instance=data, schema=schema)
            return True, "Valid"
        except jsonschema.ValidationError as e:
            error_msg = f"Schema validation error at path '{list(e.path)}': {e.message}"
            return False, error_msg
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def assert_valid(self, data: Dict[str, Any], schema_filename: str) -> None:
        """Validates and raises SchemaValidationError if invalid."""
        is_valid, msg = self.validate(data, schema_filename)
        if not is_valid:
            raise SchemaValidationError(f"Validation failed for schema '{schema_filename}': {msg}")
