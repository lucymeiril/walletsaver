import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import s from './Input.module.css';

export default function Input({
  label,
  error,
  helperText,
  icon: Icon,
  type = 'text',
  disabled = false,
  className = '',
  id,
  ...props
}) {
  const [showPassword, setShowPassword] = useState(false);
  const inputId = id || `input-${label?.replace(/\s+/g, '-').toLowerCase() || Math.random().toString(36).slice(2)}`;
  const inputType = type === 'password' && showPassword ? 'text' : type;

  return (
    <div className={`${s.wrapper} ${error ? s.hasError : ''} ${disabled ? s.disabled : ''} ${className}`}>
      {label && <label htmlFor={inputId} className={s.label}>{label}</label>}
      <div className={s.inputWrap}>
        {Icon && <Icon className={s.icon} size={18} />}
        <input
          id={inputId}
          type={inputType}
          disabled={disabled}
          className={`${s.input} ${Icon ? s.hasIcon : ''} ${type === 'password' ? s.hasToggle : ''}`}
          aria-invalid={!!error}
          aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
          {...props}
        />
        {type === 'password' && (
          <button
            type="button"
            className={s.toggle}
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? '비밀번호 숨기기' : '비밀번호 보기'}
            tabIndex={-1}
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      </div>
      {error && <p id={`${inputId}-error`} className={s.error} role="alert">{error}</p>}
      {!error && helperText && <p id={`${inputId}-helper`} className={s.helper}>{helperText}</p>}
    </div>
  );
}
