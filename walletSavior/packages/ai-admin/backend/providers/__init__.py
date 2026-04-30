"""Provider adapters for ai-admin.

Adapters are local-only runtime integrations. They resolve secrets from
environment variable aliases and never store or return secret values.
"""

from .google_genai import GoogleGenAIProvider

__all__ = ["GoogleGenAIProvider"]
