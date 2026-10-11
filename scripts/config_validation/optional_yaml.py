from __future__ import annotations

from pathlib import Path
from types import ModuleType

from scripts.config_validation.yaml_helpers import check_yaml_mapping, load_yaml_mapping


def validate_search(path: Path, yaml: ModuleType) -> list[str]:
    """Return errors for an optional search/research YAML config."""
    if not path.exists():
        return []
    return check_yaml_mapping(path, yaml)


def validate_glossary(path: Path, yaml: ModuleType) -> list[str]:
    """Return errors for the optional digest glossary config."""
    if not path.exists():
        return []
    errors, data = load_yaml_mapping(path, yaml)
    if errors or data is None:
        return errors

    terms = data.get("terms")
    if not isinstance(terms, dict):
        errors.append(
            f"{path.name}: `terms:` must be a mapping of term → explanation"
        )
        return errors
    for term, explanation in terms.items():
        if not isinstance(term, str) or not isinstance(explanation, str):
            errors.append(
                f"{path.name}: term `{term}` must map a string term to a "
                "string explanation"
            )
    return errors


def validate_tags(path: Path, yaml: ModuleType) -> list[str]:
    """Return errors for tags.yaml controlled vocabulary config."""
    errors, data = load_yaml_mapping(path, yaml)
    if errors or data is None:
        return errors

    domains = data.get("domains")
    if domains is not None:
        if not isinstance(domains, dict):
            errors.append(f"{path.name}: `domains:` must be a mapping")
        else:
            for domain, topics in domains.items():
                if topics is not None and not isinstance(topics, list):
                    errors.append(
                        f"{path.name}: domain `{domain}` must map to a list of "
                        "topics (or be empty)"
                    )

    synonyms = data.get("synonyms")
    if synonyms is not None and not isinstance(synonyms, dict):
        errors.append(f"{path.name}: `synonyms:` must be a mapping of alias → canonical")

    pending = data.get("pending")
    if pending is not None and not isinstance(pending, list):
        errors.append(f"{path.name}: `pending:` must be a list")
    return errors


__all__ = ["validate_glossary", "validate_search", "validate_tags"]
