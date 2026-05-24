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
  last_login_at: string | null
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

// ── API Key Management ──────────────────────────────────────────────────────

export interface ApiKey {
  id: number
  name: string
  key_prefix: string
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreateResponse {
  id: number
  name: string
  key: string
  key_prefix: string
  created_at: string | null
}

export function listApiKeys(): Promise<ApiKey[]> {
  return api.get<ApiKey[]>('/api/users/me/api-keys')
}

export function createApiKey(name: string): Promise<ApiKeyCreateResponse> {
  return api.post<ApiKeyCreateResponse>('/api/users/me/api-keys', { name })
}

export function revokeApiKey(keyId: number): Promise<{ message: string }> {
  return api.post<{ message: string }>(`/api/users/me/api-keys/${keyId}/revoke`)
}

export function deleteApiKey(keyId: number): Promise<{ message: string }> {
  return api.delete<{ message: string }>(`/api/users/me/api-keys/${keyId}`)
}
