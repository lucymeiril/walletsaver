import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchAutocomplete } from '../api/client'
import type { AutocompleteSuggestion } from '../types'

interface SearchBarProps {
  initialQuery?: string
  onSearch?: (q: string) => void
}

export function SearchBar({ initialQuery = '', onSearch }: SearchBarProps) {
  const [query, setQuery] = useState(initialQuery)
  const [suggestions, setSuggestions] = useState<AutocompleteSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()

  const triggerAutocomplete = useCallback((value: string) => {
    if (value.trim().length === 0) {
      setSuggestions([])
      setOpen(false)
      return
    }
    fetchAutocomplete(value)
      .then((res) => {
        setSuggestions(res.suggestions)
        setOpen(res.suggestions.length > 0)
      })
      .catch(() => {
        setSuggestions([])
        setOpen(false)
      })
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => triggerAutocomplete(query), 200)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, triggerAutocomplete])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setOpen(false)
    if (onSearch) {
      onSearch(query)
    } else {
      navigate(`/?q=${encodeURIComponent(query)}`)
    }
  }

  const handleSuggestionClick = (s: AutocompleteSuggestion) => {
    setQuery(s.display)
    setOpen(false)
    if (onSearch) {
      onSearch(s.display)
    } else {
      navigate(`/?q=${encodeURIComponent(s.display)}`)
    }
  }

  return (
    <div style={{ position: 'relative', width: '100%', maxWidth: '600px' }}>
      <form onSubmit={handleSubmit} role="search">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="상품 검색 (예: 두부, 계란, 라면)"
          aria-label="상품 검색"
          style={{
            width: '100%',
            padding: '10px 16px',
            fontSize: '16px',
            border: '2px solid #e5e7eb',
            borderRadius: '8px',
            boxSizing: 'border-box',
          }}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </form>
      {open && suggestions.length > 0 && (
        <ul
          role="listbox"
          aria-label="자동완성 목록"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: '8px',
            listStyle: 'none',
            margin: 0,
            padding: '4px 0',
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
          }}
        >
          {suggestions.map((s, i) => (
            <li
              key={i}
              role="option"
              aria-selected={false}
              onMouseDown={() => handleSuggestionClick(s)}
              style={{
                padding: '8px 16px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>{s.display}</span>
              <small style={{ color: '#9ca3af' }}>{s.source}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
