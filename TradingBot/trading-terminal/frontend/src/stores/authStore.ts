import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { setAuthToken } from '@/lib/api/client'

interface AuthState {
  token: string | null
  username: string | null
  login: (token: string, username: string) => void
  logout: () => void
  isAuthenticated: boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      isAuthenticated: false,
      login: (token, username) => {
        setAuthToken(token)
        set({ token, username, isAuthenticated: true })
      },
      logout: () => {
        setAuthToken('')
        set({ token: null, username: null, isAuthenticated: false })
      },
    }),
    {
      name: 'trading-terminal-auth',
      onRehydrateStorage: () => (state) => {
        if (state?.token) setAuthToken(state.token)
      },
    }
  )
)
