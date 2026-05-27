import DOMPurify from 'dompurify';

const RICH_TEXT_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'strong', 'em', 'u', 's', 'del',
    'h1', 'h2', 'h3', 'h4',
    'ul', 'ol', 'li',
    'a', 'img',
    'blockquote', 'pre', 'code',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr', 'span', 'div',
  ],
  ALLOWED_ATTR: [
    'href', 'title', 'target', 'rel',
    'src', 'alt', 'width', 'height',
    'class', 'style',
  ],
  ALLOW_DATA_ATTR: false,
  ADD_ATTR: ['target'],
};

const PLAIN_TEXT_CONFIG = {
  ALLOWED_TAGS: [],
  ALLOWED_ATTR: [],
};

/**
 * Sanitize rich HTML content (community post body).
 * Defense-in-depth: backend also sanitizes before storage.
 */
export function sanitizeHTML(dirty) {
  if (!dirty) return '';
  const clean = DOMPurify.sanitize(dirty, RICH_TEXT_CONFIG);
  return clean;
}

/**
 * Strip all HTML — for titles, nicknames, categories.
 */
export function stripHTML(dirty) {
  if (!dirty) return '';
  return DOMPurify.sanitize(dirty, PLAIN_TEXT_CONFIG);
}

/**
 * Validate URL: only allow http(s) protocols.
 * Blocks javascript:, data:, vbscript:, etc.
 */
export function sanitizeURL(url) {
  if (!url) return '';
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return '';
    }
    return url;
  } catch {
    return '';
  }
}

// Hook: force all <a> tags to have rel="noopener noreferrer"
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
  if (node.tagName === 'IMG') {
    const src = node.getAttribute('src') || '';
    if (src && !src.startsWith('https://') && !src.startsWith('http://') && !src.startsWith('data:image/')) {
      node.removeAttribute('src');
    }
  }
});
