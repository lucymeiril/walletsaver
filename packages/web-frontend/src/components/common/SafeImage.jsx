import { useState, useCallback } from 'react';
import s from './SafeImage.module.css';

const FALLBACK_ICON = (
  <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21,15 16,10 5,21"/>
  </svg>
);

export default function SafeImage({
  src,
  alt = '',
  className = '',
  fallbackClassName = '',
  loading = 'lazy',
  ...props
}) {
  const [hasError, setHasError] = useState(false);
  const [imgSrc, setImgSrc] = useState(src);

  const handleError = useCallback(() => setHasError(true), []);

  // Reset error state when src prop changes
  if (src !== imgSrc && !hasError) {
    setImgSrc(src);
  }
  if (src !== imgSrc && hasError) {
    setImgSrc(src);
    setHasError(false);
  }

  if (hasError || !src) {
    return (
      <div
        className={`${s.fallback} ${fallbackClassName || className}`}
        role="img"
        aria-label={alt || '이미지를 불러올 수 없습니다'}
      >
        {FALLBACK_ICON}
      </div>
    );
  }

  return (
    <img
      src={imgSrc}
      alt={alt}
      className={className}
      loading={loading}
      onError={handleError}
      {...props}
    />
  );
}
