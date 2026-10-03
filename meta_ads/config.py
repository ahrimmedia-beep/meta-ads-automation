"""Credentials from a .env file. Values are never printed."""
import sys


def load_env(path, required=("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    missing = [k for k in required if not env.get(k)]
    if missing:
        sys.exit(f".env: missing {', '.join(missing)}")
    return env
