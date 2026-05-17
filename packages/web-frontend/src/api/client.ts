import type {
  AutocompleteSuggestion,
  SearchResult,
  ProductDetail,
  FuelSearchResult,
  FuelRegions,
  FuelStationDetail,
  Board,
  BoardCategory,
  PaginatedPosts,
  PostDetail,
  Comment as BoardComment,
  VerdictSummary,
  AuthUser,
  Report,
  AuditEntry,
} from '../types'

const BASE = '/api/v1'

async function jfetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: 'include', ...init })
  if (!res.ok) throw new Error(`${url} ${res.status}`)
  return res.json() as Promise<T>
}

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

// ── Fuel API ──────────────────────────────────────────────────────────────────

export async function fetchFuelRegions(sido?: string): Promise<FuelRegions> {
  const url = new URL(`${BASE}/fuels/regions`, window.location.origin)
  if (sido) url.searchParams.set('sido', sido)
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`fuels/regions ${res.status}`)
  return res.json()
}

export async function searchFuelStations(params: {
  sido?: string
  sigungu?: string
  brand?: string
  fuel_kind?: string
  sort?: string
  lat?: number
  lng?: number
  radius_km?: number
  page?: number
  page_size?: number
}): Promise<FuelSearchResult> {
  const url = new URL(`${BASE}/fuels/stations`, window.location.origin)
  if (params.sido) url.searchParams.set('sido', params.sido)
  if (params.sigungu) url.searchParams.set('sigungu', params.sigungu)
  if (params.brand) url.searchParams.set('brand', params.brand)
  if (params.fuel_kind) url.searchParams.set('fuel_kind', params.fuel_kind)
  if (params.sort) url.searchParams.set('sort', params.sort)
  if (params.lat != null) url.searchParams.set('lat', String(params.lat))
  if (params.lng != null) url.searchParams.set('lng', String(params.lng))
  if (params.radius_km != null) url.searchParams.set('radius_km', String(params.radius_km))
  if (params.page) url.searchParams.set('page', String(params.page))
  if (params.page_size) url.searchParams.set('page_size', String(params.page_size))
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`fuels/stations ${res.status}`)
  return res.json()
}

export async function fetchFuelStation(stationId: string): Promise<FuelStationDetail> {
  const res = await fetch(`${BASE}/fuels/stations/${stationId}`)
  if (!res.ok) throw new Error(`fuels/stations/${stationId} ${res.status}`)
  return res.json()
}

// ── F2: Auth ──────────────────────────────────────────────────────────────────

export async function register(email: string, displayName: string, password: string): Promise<AuthUser> {
  return jfetch<AuthUser>(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name: displayName, password }),
  })
}

export async function login(email: string, password: string): Promise<AuthUser> {
  return jfetch<AuthUser>(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, { method: 'POST', credentials: 'include' })
}

export async function fetchMe(): Promise<AuthUser | null> {
  const res = await fetch(`${BASE}/auth/me`, { credentials: 'include' })
  if (res.status === 401) return null
  if (!res.ok) throw new Error(`me ${res.status}`)
  return res.json()
}

// ── F2: Boards / Posts / Comments ─────────────────────────────────────────────

export async function fetchBoards(): Promise<Board[]> {
  return jfetch<Board[]>(`${BASE}/boards`)
}

export async function fetchBoardCategories(slug: string): Promise<BoardCategory[]> {
  return jfetch<BoardCategory[]>(`${BASE}/boards/${slug}/categories`)
}

export async function fetchBoardPosts(
  slug: string,
  params: { category?: string; q?: string; page?: number; page_size?: number; sort?: string } = {}
): Promise<PaginatedPosts> {
  const url = new URL(`${BASE}/boards/${slug}/posts`, window.location.origin)
  if (params.category) url.searchParams.set('category', params.category)
  if (params.q) url.searchParams.set('q', params.q)
  if (params.page) url.searchParams.set('page', String(params.page))
  if (params.page_size) url.searchParams.set('page_size', String(params.page_size))
  if (params.sort) url.searchParams.set('sort', params.sort)
  return jfetch<PaginatedPosts>(url.toString())
}

export async function createPost(slug: string, formData: FormData): Promise<PostDetail> {
  const res = await fetch(`${BASE}/boards/${slug}/posts`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`createPost ${res.status}`)
  return res.json()
}

export async function fetchPost(id: string): Promise<PostDetail> {
  return jfetch<PostDetail>(`${BASE}/posts/${id}`)
}

export async function deletePost(id: string): Promise<void> {
  const res = await fetch(`${BASE}/posts/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`deletePost ${res.status}`)
}

export async function createComment(
  postId: string,
  body: string,
  verdict: 'hot_deal' | 'not_hot_deal' | 'neutral' = 'neutral'
): Promise<BoardComment> {
  return jfetch<BoardComment>(`${BASE}/posts/${postId}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body, verdict }),
  })
}

export async function reportPost(postId: string, reason: string): Promise<void> {
  await jfetch(`${BASE}/posts/${postId}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export async function reportComment(commentId: string, reason: string): Promise<void> {
  await jfetch(`${BASE}/comments/${commentId}/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
}

export async function fetchVerdictSummary(postId: string): Promise<VerdictSummary> {
  return jfetch<VerdictSummary>(`${BASE}/posts/${postId}/verdict-summary`)
}

// ── F2: Moderation / Admin ────────────────────────────────────────────────────

export async function fetchReports(status: string = 'open'): Promise<Report[]> {
  return jfetch<Report[]>(`${BASE}/reports?status=${encodeURIComponent(status)}`)
}

export async function resolveReport(
  id: string,
  action: 'hide_target' | 'delete_target' | 'dismiss' | 'ban_user',
  note?: string
): Promise<void> {
  await jfetch(`${BASE}/reports/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, note }),
  })
}

export async function banUser(id: string): Promise<void> {
  await jfetch(`${BASE}/users/${id}/ban`, { method: 'POST' })
}

export async function unbanUser(id: string): Promise<void> {
  await jfetch(`${BASE}/users/${id}/unban`, { method: 'POST' })
}

export async function fetchAuditLog(): Promise<AuditEntry[]> {
  return jfetch<AuditEntry[]>(`${BASE}/admin/audit`)
}
