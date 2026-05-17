import type { AutocompleteSuggestion, SearchResult, ProductDetail } from '../types'

const BASE = '/api/v1'

export async function fetchHealth() {
  const res = await fetch(`${BASE}/health`)
  if (!res.ok) throw new Error(`health ${res.status}`)
  return res.json()
}

export async function fetchCategories() {
  const res = await fetch(`${BASE}/categories`)
  if (!res.ok) throw new Error(`categories ${res.status}`)
  return res.json()
}

export async function searchProducts(params: {
  q?: string
  category?: string
  page?: number
  sort?: string
}): Promise<SearchResult> {
  const url = new URL(`${BASE}/products/search`, window.location.origin)
  if (params.q) url.searchParams.set('q', params.q)
  if (params.category) url.searchParams.set('category', params.category)
  if (params.page) url.searchParams.set('page', String(params.page))
  if (params.sort) url.searchParams.set('sort', params.sort)
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`search ${res.status}`)
  return res.json()
}

export async function fetchProduct(canonicalId: string): Promise<ProductDetail> {
  const res = await fetch(`${BASE}/products/${canonicalId}`)
  if (!res.ok) throw new Error(`product ${res.status}`)
  return res.json()
}

export async function fetchAutocomplete(
  prefix: string,
  limit = 10
): Promise<{ prefix: string; suggestions: AutocompleteSuggestion[] }> {
  const res = await fetch(
    `${BASE}/autocomplete?prefix=${encodeURIComponent(prefix)}&limit=${limit}`
  )
  if (!res.ok) throw new Error(`autocomplete ${res.status}`)
  return res.json()
}
