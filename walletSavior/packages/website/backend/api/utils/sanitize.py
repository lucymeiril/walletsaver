"""
HTML sanitization utilities for user-generated content.
Defense-in-depth: sanitizes BEFORE storage so malicious content
never enters the database.
"""

import re
from urllib.parse import urlparse

import nh3

# Tags allowed in rich-text community post content
RICH_TEXT_TAGS = {
    "p", "br", "strong", "em", "u", "s", "del",
    "h1", "h2", "h3", "h4",
    "ul", "ol", "li",
    "a", "img",
    "blockquote", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "hr", "span", "div",
}

# Attributes allowed per tag
RICH_TEXT_ATTRS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "span": {"class"},
    "div": {"class"},
}

# URL schemes allowed in href/src attributes
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(dirty: str) -> str:
    """
    Sanitize rich HTML content (community post body).
    Strips all tags/attributes not in the allowlist.
    """
    if not dirty:
        return ""

    clean = nh3.clean(
        dirty,
        tags=RICH_TEXT_TAGS,
        attributes=RICH_TEXT_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    return clean


def strip_html(dirty: str) -> str:
    """Strip ALL HTML tags. For plain-text fields: title, nickname, category."""
    if not dirty:
        return ""
    return nh3.clean(dirty, tags=set())


def sanitize_nickname(nickname: str) -> str:
    """
    Allow only Korean, alphanumeric, and underscore characters.
    Strips everything else.
    """
    if not nickname:
        return ""
    cleaned = re.sub(r"[^가-힣a-zA-Z0-9_]", "", nickname)
    return cleaned[:20]


def validate_url(url: str) -> str | None:
    """
    Validate a URL: must be http or https scheme.
    Returns the URL if valid, None if not.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return url
    except Exception:
        return None


def validate_image_url(url: str) -> str | None:
    """
    Validate an image URL. Only http(s) and data:image/* allowed.
    Blocks javascript:, vbscript:, data:text/html, etc.
    """
    if not url:
        return None

    # Allow data:image URIs (from RichTextEditor base64 uploads)
    if url.startswith("data:image/"):
        # Cap data URI size at 5MB encoded
        if len(url) > 5 * 1024 * 1024 * 1.37:  # base64 inflation
            return None
        # Block SVG data URIs (can contain JS)
        if url.startswith("data:image/svg"):
            return None
        return url

    return validate_url(url)
