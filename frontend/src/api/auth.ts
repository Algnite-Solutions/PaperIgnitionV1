import { api } from './client'

export interface LoginResponse {
  access_token: string
  token_type: string
  needs_interest_setup: boolean
  user_info: {
    email: string
    username: string
  }
}

export function loginEmail(email: string, password: string): Promise<LoginResponse> {
  return api.post<LoginResponse>('/api/auth/login-email', { email, password })
}

export function registerEmail(
  email: string,
  password: string,
  username: string,
): Promise<LoginResponse> {
  return api.post<LoginResponse>('/api/auth/register-email', { email, password, username })
}
