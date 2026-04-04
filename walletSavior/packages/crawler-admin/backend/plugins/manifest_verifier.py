"""HMAC-SHA256 plugin manifest verification."""

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _get_signing_key() -> bytes:
    """Load the plugin signing key from environment."""
    key = os.getenv("PLUGIN_SIGNING_KEY", "")
    if not key:
        raise RuntimeError(
            "PLUGIN_SIGNING_KEY environment variable is required for plugin verification. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return key.encode("utf-8")


def compute_manifest_signature(manifest_data: dict[str, Any]) -> str:
    """
    Compute HMAC-SHA256 signature over the manifest content.

    Excludes the 'signature' field itself from the computation.
    Produces a deterministic digest by sorting keys and using
    consistent YAML serialization.
    """
    signable = {k: v for k, v in manifest_data.items() if k != "signature"}
    canonical = yaml.dump(signable, default_flow_style=False, sort_keys=True)
    key = _get_signing_key()
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_manifest(yaml_path: Path) -> None:
    """
    Sign a plugin.yaml file in place.

    Reads the manifest, computes the HMAC-SHA256 signature,
    and writes it back with a 'signature' field appended.
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}

    manifest["signature"] = compute_manifest_signature(manifest)

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info("Signed manifest: %s", yaml_path)


def verify_manifest(yaml_path: Path, manifest_data: dict[str, Any]) -> bool:
    """
    Verify the HMAC-SHA256 signature of a plugin manifest.

    Returns True if the signature matches, False otherwise.
    """
    stored_sig = manifest_data.get("signature")
    if not stored_sig:
        logger.error("Manifest has no signature: %s", yaml_path)
        return False

    expected = compute_manifest_signature(manifest_data)
    if not hmac.compare_digest(stored_sig, expected):
        logger.error(
            "Manifest signature mismatch: %s (expected=%s, got=%s)",
            yaml_path,
            expected[:12] + "...",
            stored_sig[:12] + "...",
        )
        return False

    return True


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file for audit logging."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()
