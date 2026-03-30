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

export function verifyEmail(token: string): Promise<{ message: string }> {
  return api.get<{ message: string }>(`/api/auth/verify-email?token=${encodeURIComponent(token)}`)
}

export function forgotPassword(email: string): Promise<{ message: string }> {
  return api.post<{ message: string }>('/api/auth/forgot-password', { email })
}

export function resetPassword(token: string, new_password: string): Promise<{ message: string }> {
  return api.post<{ message: string }>('/api/auth/reset-password', { token, new_password })
}

export function resendVerification(): Promise<{ message: string }> {
  return api.post<{ message: string }>('/api/auth/resend-verification')
}
