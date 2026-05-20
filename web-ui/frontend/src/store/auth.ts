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

  private formatError(data: any, fallback: string) {
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map((item: any) => item?.msg || item?.message)
        .filter(Boolean)
        .join('；') || fallback
    }
    return data?.detail || data?.message || fallback
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
    this.loading = true
    try {
      const response = await fetch(`${SERVER_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: email.trim(), password })
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(this.formatError(data, '登录失败'))
      }
      runInAction(() => {
        this.user = data.user
        this.quota = data.quota
        this.initialized = true
      })
      return data.user
    } finally {
      runInAction(() => {
        this.loading = false
      })
    }
  }

  async register(email: string, password: string, display_name: string) {
    this.loading = true
    try {
      const response = await fetch(`${SERVER_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: email.trim(), password, display_name: display_name.trim() })
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(this.formatError(data, '注册失败'))
      }
      runInAction(() => {
        this.user = data.user
        this.quota = data.quota
        this.initialized = true
      })
      return data.user
    } finally {
      runInAction(() => {
        this.loading = false
      })
    }
  }

  async logout() {
    try {
      await fetch(`${SERVER_URL}/auth/logout`, {
        method: 'POST',
        credentials: 'include'
      })
    } finally {
      runInAction(() => {
        this.user = null
        this.quota = null
        this.initialized = true
      })
    }
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
