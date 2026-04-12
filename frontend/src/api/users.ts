import { api } from './client'

export interface BoosterStatus {
  new_likes_count: number
  eligible: boolean
  requested: boolean
  pool_size: number
  best_f1: number | null
}

export interface UserProfile {
  id: number
  username: string
  email: string
  is_active: boolean
  is_verified: boolean
  research_interests_text: string | null
  rewrite_interest: string | null
  profile_json: Record<string, unknown> | null
  blog_language: string | null
  research_domain_ids: number[]
  activity_data: {
    favorite_count: number
    viewed_count: number
    days_active: number
  }
  booster_status: BoosterStatus | null
}

export interface ProfileUpdatePayload {
  email?: string
  research_interests_text?: string
  research_domain_ids?: number[]
  profile_json?: Record<string, unknown>
  blog_language?: string
}

export function getMe(): Promise<UserProfile> {
  return api.get<UserProfile>('/api/users/me')
}

export function updateProfile(data: ProfileUpdatePayload): Promise<UserProfile> {
  return api.put<UserProfile>('/api/users/me/profile', data)
}

export function triggerBoost(): Promise<UserProfile> {
  return api.post<UserProfile>('/api/users/me/boost', {})
}

export interface ResearchDomain {
  id: number
  name: string
}

export function getDomains(): Promise<ResearchDomain[]> {
  return api.get<ResearchDomain[]>('/api/domains')
}
