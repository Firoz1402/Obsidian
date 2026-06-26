from typing import Any, Iterable

REDACTED = "***"

_SENSITIVE_KEYS = frozenset({
    "password",
    "passwd",
    "id_token",
    "refresh_token",
    "access_token",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "credentials",
    "client_secret",
    "private_key",
})


def redact(value: Any, sensitive_keys: Iterable[str] = _SENSITIVE_KEYS) -> Any:
    keys = {k.lower() for k in sensitive_keys}
    return _walk(value, keys)


def _walk(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if k.lower() in keys else _walk(v, keys)) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(item, keys) for item in value]
    if isinstance(value, tuple):
        return tuple(_walk(item, keys) for item in value)
    return value


def clip(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + f"...[clipped {len(encoded) - max_bytes}B]"
