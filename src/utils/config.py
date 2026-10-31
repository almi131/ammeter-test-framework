import re
from typing import Dict

import yaml

NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


class ConfigError(ValueError):
    """Invalid or inconsistent configuration."""


def check_name(name) -> str:
    """Ammeter names end up in file names, so only letters, digits, '_' and '-' are allowed."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ConfigError(f"Invalid ammeter name {name!r}: use only letters, digits, '_' and '-'")
    return name


def section(cfg: Dict, key: str) -> Dict:
    """cfg[key] as a dict; a missing or empty section gives {}."""
    value = cfg.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"Config section '{key}' must be a mapping, got {type(value).__name__}")
    return value


def load_config(config_path: str) -> Dict:
    """Load a YAML config file (a missing file raises FileNotFoundError)."""
    with open(config_path, "r", encoding="utf-8") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e
    if config is None:
        raise ConfigError(f"Config file {config_path} is empty")
    if not isinstance(config, dict):
        raise ConfigError(f"Config file {config_path} must contain a mapping at the top level, "
                          f"got {type(config).__name__}")
    return config
