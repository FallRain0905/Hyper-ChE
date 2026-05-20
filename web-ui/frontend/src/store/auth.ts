import { makeAutoObservable, runInAction } from 'mobx'
import { SERVER_URL } from '../utils'

export interface HyperChEUser {
  id: string
  email: string
  display_name: string
  role: string
}

export interface QuotaInfo {
  trial_docs_used: number
  trial_docs_limit: number
  trial_llm_calls_used: number
  trial_llm_calls_limit: number
  trial_embedding_calls_used: number
  trial_embedding_calls_limit: number
  monthly_reset_at?: string
}

class AuthStore {
  user: HyperChEUser | null = null
  quota: QuotaInfo | null = null
  loading = false
  initialized = false

  constructor() {
    makeAutoObservable(this)
  }

  get isAuthenticated() {
    return !!this.user
  }

  async fetchMe() {
    this.loading = true
    try {
      const response = await fetch(`${SERVER_URL}/auth/me`, {
        credentials: 'include'
      })
      if (!response.ok) {
        runInAction(() => {
          this.user = null
          this.quota = null
          this.initialized = true
        })
        return null
      }
      const data = await response.json()
      runInAction(() => {
        this.user = data.user
        this.quota = data.quota
        this.initialized = true
      })
      return data.user
    } finally {
      runInAction(() => {
        this.loading = false
        this.initialized = true
      })
    }
  }

  async login(email: string, password: string) {
    const response = await fetch(`${SERVER_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password })
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(data.detail || data.message || '登录失败')
    }
    runInAction(() => {
      this.user = data.user
      this.quota = data.quota
      this.initialized = true
    })
    return data.user
  }

  async register(email: string, password: string, display_name: string) {
    const response = await fetch(`${SERVER_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password, display_name })
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(data.detail || data.message || '注册失败')
    }
    runInAction(() => {
      this.user = data.user
      this.quota = data.quota
      this.initialized = true
    })
    return data.user
  }

  async logout() {
    await fetch(`${SERVER_URL}/auth/logout`, {
      method: 'POST',
      credentials: 'include'
    })
    runInAction(() => {
      this.user = null
      this.quota = null
      this.initialized = true
    })
  }

  async refreshQuota() {
    const response = await fetch(`${SERVER_URL}/quota/me`, {
      credentials: 'include'
    })
    if (response.ok) {
      const data = await response.json()
      runInAction(() => {
        this.quota = data.quota
      })
    }
  }
}

export const authStore = new AuthStore()
