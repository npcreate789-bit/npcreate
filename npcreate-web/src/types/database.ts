export type Portfolio = {
  id: string
  title: string
  slug: string
  client_name: string | null
  client_logo: string | null
  industry: string | null
  service_type: string[]
  short_desc: string | null
  challenge: string | null
  strategy: string | null
  result: string | null
  gmv_before: number | null
  gmv_after: number | null
  gmv_growth_pct: number | null
  roas: number | null
  ad_spend: number | null
  duration_days: number | null
  cover_image: string | null
  is_featured: boolean
  is_published: boolean
  display_order: number
  created_at: string
  updated_at: string
}

export type PortfolioMedia = {
  id: string
  portfolio_id: string
  media_type: 'image' | 'video' | 'tiktok_embed' | 'youtube_embed'
  url: string | null
  thumbnail_url: string | null
  embed_code: string | null
  caption: string | null
  display_order: number
  created_at: string
}

export type Service = {
  id: string
  title: string
  slug: string
  short_desc: string | null
  full_desc: string | null
  icon: string | null
  features: { title: string; desc: string }[]
  starting_price: string | null
  is_popular: boolean
  display_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export type Testimonial = {
  id: string
  client_name: string
  client_role: string | null
  client_company: string | null
  client_avatar: string | null
  content: string
  short_quote: string | null
  rating: number | null
  related_portfolio_id: string | null
  is_featured: boolean
  display_order: number
  created_at: string
}

export type ClientLogo = {
  id: string
  name: string
  logo_url: string
  website_url: string | null
  display_order: number
  created_at: string
}