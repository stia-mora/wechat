export interface Profile {
  profile_summary: string;
  account_type: string;
  target_audience: string[];
  content_style: string[];
  expertise_level: string;
  topic_distribution: { name: string; percentage: number }[];
  strengths: string[];
  weaknesses: string[];
  recommendation_reason: string;
  not_recommended_for: string[];
  quality_scores: Record<string, number | null>;
  scoring_version?: string;
  overall_score?: number | null;
  sample_policy?: string;
  assessments?: { dimension: string; score: number | null; reason: string; limitation: string; evidence: {article_id: number; quote: string}[] }[];
}
export interface Account {
  id: number;
  name: string;
  source_id: string;
  wechat_id: string;
  avatar_url: string;
  description: string;
  category: string | null;
  primary_category_id: number | null;
  tags: string[];
  account_type: string;
  status: string;
  article_count: number;
  articles_last_7d: number;
  articles_last_30d: number;
  readable_count: number;
  following_count: number;
  collection_count: number;
  growth: number;
  profile: Profile | null;
  rank_score: number;
  rank_factors: Record<string, number>;
  quality_score: number | null;
  quality_comparison?: {count: number; percentile: number} | null;
  recommendation_reason: string;
  last_crawled_at: string | null;
  last_article_at: string | null;
  model_name: string | null;
  prompt_version: string | null;
  source_article_count: number | null;
  generated_at: string | null;
  following?: boolean;
  collected?: boolean;
  similar?: Account[];
  similarity?: number;
  similarity_reason?: string;
  difference?: string;
  source_url: string;
  subcategories?: Category[];
}
export interface Article {
  id: number;
  account_id: number;
  title: string;
  account_name: string;
  author: string;
  source_url: string;
  cover_url: string;
  publish_time: string | null;
  summary: string;
  status: string;
  word_count: number;
  content_html?: string;
  content_text?: string;
  category?: string;
  collected?: boolean;
  ai_summary?: {
    summary: string;
    key_points: string[];
    keywords: string[];
    target_audience: string[];
    quality_score: number;
  };
  model_name?: string;
  generated_at?: string;
  related?: Article[];
}
export interface Category {
  id: number;
  name: string;
  slug: string;
  parent_id: number | null;
  account_count: number;
  status: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}
export interface User {
  id: number;
  email: string;
  display_name: string;
}
export interface Job {
  id: number;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  error: string | null;
  attempts: number;
  created_at: string;
  result: Record<string, unknown> | null;
}
