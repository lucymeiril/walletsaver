"""Provider adapters for ai-admin.

Adapters are local-only runtime integrations. They resolve secrets from
environment variable aliases and never store or return secret values.
"""

from .google_genai import GoogleGenAIProvider
from .wire_logger import WireLogger, attach_wire_logger_to_genai_client, get_wire_logger_from_env

__all__ = [
    "GoogleGenAIProvider",
    "WireLogger",
    "attach_wire_logger_to_genai_client",
    "get_wire_logger_from_env",
]
