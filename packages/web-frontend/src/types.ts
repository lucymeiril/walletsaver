export interface CategoryNode {
  id: string
  name_kr: string
  name_slug: string
  level: number
  path: string
  parent_id: string | null
  children: CategoryNode[]
}

export interface PriceGrade {
  p10: number | null
  p25: number | null
  p50: number | null
  p75: number | null
  sufficient: boolean
  sample_size: number
  grade_label: GradeLabel
}

export type GradeLabel =
  | 'HOT_DEAL'
  | 'SALE'
  | 'NORMAL'
  | 'OVERPRICED'
  | 'INSUFFICIENT_DATA'

export interface ProductSummary {
  canonical_id: string
  name_core: string
  brand: string | null
  pack_quantity: number | null
  pack_unit: string | null
  category_id: string | null
  image_url: string | null
  p10: number | null
  p25: number | null
  p50: number | null
  p75: number | null
  sufficient: boolean
  grade_label: GradeLabel
  marts: string[]
}

export interface MartAlias {
  mart: string
  mart_item_id: string | null
  mart_item_name_raw: string | null
  source_url: string | null
  last_seen_at: string | null
}

export interface ProductDetail {
  canonical_id: string
  name_core: string
  brand: string | null
  pack_quantity: number | null
  pack_unit: string | null
  category_id: string | null
  image_url: string | null
  price_grade: PriceGrade
  mart_aliases: MartAlias[]
}

export interface AutocompleteSuggestion {
  token: string
  display: string
  source: string
  weight: number
  canonical_id: string | null
  category_node_id: string | null
}

export interface SearchResult {
  total: number
  page: number
  page_size: number
  total_pages: number
  items: ProductSummary[]
}

// ---------- F2: Board / auth / moderation ----------

export interface BoardUser { id: string; display_name: string; role: string }
export interface AuthUser { user_id: string; email: string; display_name: string; role: string }
export interface Board { slug: string; name: string; description: string | null; category_count: number }
export interface BoardCategory { id: string; board_slug: string; name: string; slug: string }
export interface PostSummary {
  id: string
  board_slug: string
  title: string
  user: BoardUser
  category_id: string | null
  freeform_category: string | null
  deal_price: number | null
  canonical_id: string | null
  created_at: string
  comment_count: number
  hidden_at: string | null
}
export interface PostImage { id: string; ord: number; image_url: string; alt: string | null }
export interface Comment {
  id: string
  user: BoardUser
  body: string
  verdict: 'hot_deal' | 'not_hot_deal' | 'neutral'
  created_at: string
  hidden_at: string | null
}
export interface GradeSummary {
  p10: number | null
  p50: number | null
  label: string
  sufficient: boolean
}
export interface PostDetail extends PostSummary {
  body_markdown: string
  images: PostImage[]
  comments: Comment[]
  grade_summary: GradeSummary | null
  mart_name: string | null
  deal_url: string | null
}
export interface VerdictSummary { hot_deal: number; not_hot_deal: number; neutral: number }
export interface PaginatedPosts {
  total: number
  page: number
  page_size: number
  total_pages: number
  items: PostSummary[]
}
export interface Report {
  id: string
  target_kind: string
  target_id: string
  reason: string | null
  status: string
  created_at: string
  reporter_user_id: string
}
export interface AuditEntry {
  id: string
  action: string
  target_kind: string | null
  target_id: string | null
  actor_user_id: string | null
  note: string | null
  created_at: string
}

// ── Fuel 주유소 타입 ─────────────────────────────────────────────────────────

export type FuelKind = 'gasoline_regular' | 'gasoline_premium' | 'diesel' | 'lpg'

export type FuelGradeLabel = 'CHEAP' | 'NORMAL' | 'EXPENSIVE' | 'INSUFFICIENT_DATA'

export interface FuelStation {
  id: string
  brand: string
  name: string
  address: string
  sido: string
  sigungu: string
  lat: number | null
  lng: number | null
  self_service: boolean
  has_car_wash: boolean
  has_convenience: boolean
  opinet_id: string | null
  // 검색 결과 추가 필드
  price: number | null
  fuel_kind: FuelKind
  fuel_kind_label: string
  grade_label: FuelGradeLabel
  distance_km: number | null
}

export interface FuelPriceDetail {
  fuel_kind: FuelKind
  fuel_kind_label: string
  price: number
  observed_at: string
  grade_label: FuelGradeLabel
  grade: {
    p25: number | null
    p50: number | null
    p75: number | null
    sufficient: boolean
  }
}

export interface FuelStationDetail extends Omit<FuelStation, 'price' | 'fuel_kind' | 'fuel_kind_label' | 'grade_label' | 'distance_km'> {
  prices: FuelPriceDetail[]
}

export interface FuelSearchSummary {
  region: string
  fuel_kind: FuelKind
  fuel_kind_label: string
  avg_price: number | null
  min_price: number | null
  station_count: number
}

export interface FuelSearchResult {
  total: number
  page: number
  page_size: number
  total_pages: number
  summary: FuelSearchSummary
  items: FuelStation[]
}

export interface FuelRegions {
  sido_list: string[]
  sigungu_list: string[]
  brand_list: string[]
  fuel_kinds: { value: FuelKind; label: string }[]
}
