import { defineStore } from 'pinia'
import { apiAuth } from '@/api'
import { TOKEN_KEY } from '@/api/http'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    loading: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    displayName: (state) => state.user?.nickname || state.user?.username || '访客',
  },
  actions: {
    async login(payload) {
      const data = await apiAuth.login(payload)
      this.token = data.access_token
      this.user = data.user
      localStorage.setItem(TOKEN_KEY, data.access_token)
      return data
    },
    async register(payload) {
      return apiAuth.register(payload)
    },
    async fetchMe() {
      if (!this.token) return null
      try {
        this.user = await apiAuth.me()
      } catch {
        this.logout()
      }
      return this.user
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
  },
})
