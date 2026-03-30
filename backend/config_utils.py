"""
Unified Configuration Loading Utility for PaperIgnition v2
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


def _substitute_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def replace_env_var(match):
            env_var = match.group(1)
            env_value = os.environ.get(env_var)
            if env_value is None:
                logger.warning(f"Environment variable '{env_var}' not found, keeping placeholder")
                return match.group(0)
            return env_value
        return re.sub(r'\$\{([^}]+)\}', replace_env_var, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    else:
        return value


def load_config(
    config_path: Optional[str] = None,
    service: str = "backend",
    set_env: bool = True,
) -> Dict[str, Any]:
    # Load .env file if present
    try:
        from dotenv import load_dotenv
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
    except ImportError:
        pass

    if not config_path:
        config_path = os.environ.get("PAPERIGNITION_CONFIG")
    if not config_path:
        LOCAL_MODE = os.getenv("PAPERIGNITION_LOCAL_MODE", "false").lower() == "true"
        config_file = "ci_config.yaml" if LOCAL_MODE else "app_config.yaml"
        config_path = str(Path(__file__).resolve().parent / "configs" / config_file)

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at: {config_path}")

    try:
        with open(config_path, 'r') as f:
            full_config = yaml.safe_load(f)
        full_config = _substitute_env_vars(full_config)

        required_sections = {"USER_DB": "User database", "APP_SERVICE": "App service"}
        for section, desc in required_sections.items():
            if section not in full_config:
                raise ValueError(f"Missing required section '{section}' in {config_path}")

        config = {
            "USER_DB": full_config["USER_DB"],
            "APP_SERVICE": full_config["APP_SERVICE"],
            "dashscope": full_config.get("dashscope", {}),
            "aliyun_rds": full_config.get("aliyun_rds", {}),
            "aliyun_oss": full_config.get("aliyun_oss", {}),
            "smtp": full_config.get("smtp", {}),
        }

        dashscope_config = config.get("dashscope", {})
        if dashscope_config and set_env:
            for key in ("api_key", "base_url", "embedding_model", "embedding_dimension"):
                if key in dashscope_config:
                    os.environ[f"DASHSCOPE_{key.upper()}"] = str(dashscope_config[key])

        logger.info(f"Loaded configuration from: {config_path}")
        return config

    except Exception as e:
        raise ValueError(f"Error loading config from {config_path}: {str(e)}")
