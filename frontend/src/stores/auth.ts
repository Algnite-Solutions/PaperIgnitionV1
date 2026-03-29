import { create } from 'zustand'
import { loginEmail, registerEmail, type LoginResponse } from '../api/auth'
import { DEMO_EMAIL, DEMO_PASSWORD } from '../lib/constants'

interface UserInfo {
  email: string
  username: string
}

interface AuthState {
  user: UserInfo | null
  token: string | null
  isLoggedIn: boolean
  login: (email: string, password: string) => Promise<LoginResponse>
  register: (email: string, password: string, username: string) => Promise<LoginResponse>
  demoLogin: () => Promise<LoginResponse>
  logout: () => void
  hydrate: () => void
}

function persist(token: string, user: UserInfo) {
  localStorage.setItem('token', token)
  localStorage.setItem('userInfo', JSON.stringify(user))
  localStorage.setItem('userEmail', user.email)
}

function clearStorage() {
  localStorage.removeItem('token')
  localStorage.removeItem('userInfo')
  localStorage.removeItem('userEmail')
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isLoggedIn: false,

  login: async (email, password) => {
    const res = await loginEmail(email, password)
    const user = res.user_info
    persist(res.access_token, user)
    set({ user, token: res.access_token, isLoggedIn: true })
    return res
  },

  register: async (email, password, username) => {
    const res = await registerEmail(email, password, username)
    const user = res.user_info
    persist(res.access_token, user)
    set({ user, token: res.access_token, isLoggedIn: true })
    return res
  },

  demoLogin: async () => {
    const res = await loginEmail(DEMO_EMAIL, DEMO_PASSWORD)
    const user = res.user_info
    persist(res.access_token, user)
    set({ user, token: res.access_token, isLoggedIn: true })
    return res
  },

  logout: () => {
    clearStorage()
    set({ user: null, token: null, isLoggedIn: false })
  },

  hydrate: () => {
    const token = localStorage.getItem('token')
    const raw = localStorage.getItem('userInfo')
    if (token && raw) {
      try {
        const user = JSON.parse(raw) as UserInfo
        set({ user, token, isLoggedIn: true })
      } catch {
        clearStorage()
      }
    }
  },
}))
