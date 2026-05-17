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
