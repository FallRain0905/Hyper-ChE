import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { observer } from 'mobx-react'
import { Navigate } from 'react-router-dom'
import { message } from 'antd'
import {
  Activity,
  BrainCircuit,
  Database,
  Gauge,
  KeyRound,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  Users,
} from 'lucide-react'
import { authStore } from '@/store/auth'
import { SERVER_URL } from '@/utils'

type LLMProvider = {
  name: string
  baseUrl: string
  modelName: string
  apiKeys: string[]
  enabled: boolean
  maxAsync: number
  perKeyMaxAsync?: number | null
  priority: number
}

type SettingsState = {
  apiKey: string
  modelProvider: string
  modelName: string
  baseUrl: string
  selectedDatabase: string
  maxTokens: number
  temperature: number
  llmTimeout: number
  llmModelMaxAsync: number
  llmGlobalMaxAsync: number
  llmPerKeyMaxAsync: number
  llmMaxRetries: number
  llmKeyCooldownSeconds: number
  llmProviderStrategy: string
  llmProviders: LLMProvider[]
  embeddingModel: string
  embeddingDim: number
  embeddingBaseUrl: string
  embeddingApiKey: string
  enableCogRAG: boolean
  mineruApiBaseUrl: string
  mineruApiToken: string
  mineruModelVersion: string
  mineruLanguage: string
  mineruEnableOcr: boolean
  mineruEnableFormula: boolean
  mineruEnableTable: boolean
  mineruExtraFormats: string[]
  mineruPollIntervalSeconds: number
  mineruMaxPollAttempts: number
  mineruMaxFileMb: number
  mineruMaxResultMb: number
  [key: string]: any
}

type QuotaConfig = {
  trial_docs_limit: number
  trial_llm_calls_limit: number
  trial_embedding_calls_limit: number
}

type AdminUser = {
  id: string
  email: string
  display_name: string
  role: string
  created_at?: string
  last_login_at?: string
  quota: {
    trial_docs_used: number
    trial_docs_limit: number
    trial_llm_calls_used: number
    trial_llm_calls_limit: number
    trial_embedding_calls_used: number
    trial_embedding_calls_limit: number
    daily_reset_at?: string
    unlimited?: boolean
  }
}

const defaultSettings: SettingsState = {
  apiKey: '',
  modelProvider: 'openai',
  modelName: 'gpt-5-mini',
  baseUrl: 'https://api.openai.com/v1',
  selectedDatabase: '',
  maxTokens: 2000,
  temperature: 0.7,
  llmTimeout: 600,
  llmModelMaxAsync: 16,
  llmGlobalMaxAsync: 16,
  llmPerKeyMaxAsync: 4,
  llmMaxRetries: 1,
  llmKeyCooldownSeconds: 60,
  llmProviderStrategy: 'priority_round_robin',
  llmProviders: [],
  embeddingModel: 'text-embedding-3-small',
  embeddingDim: 1536,
  embeddingBaseUrl: '',
  embeddingApiKey: '',
  enableCogRAG: true,
  mineruApiBaseUrl: 'https://mineru.net/api/v4',
  mineruApiToken: '',
  mineruModelVersion: 'pipeline',
  mineruLanguage: 'ch',
  mineruEnableOcr: true,
  mineruEnableFormula: true,
  mineruEnableTable: true,
  mineruExtraFormats: ['docx', 'html'],
  mineruPollIntervalSeconds: 3,
  mineruMaxPollAttempts: 100,
  mineruMaxFileMb: 200,
  mineruMaxResultMb: 300,
}

const defaultQuota: QuotaConfig = {
  trial_docs_limit: 3,
  trial_llm_calls_limit: 50,
  trial_embedding_calls_limit: 200,
}

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(`${SERVER_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data?.success === false) {
    throw new Error(data?.detail || data?.message || `请求失败（${response.status}）`)
  }
  return data
}

const Section = ({ icon, title, desc, children }: { icon: ReactNode; title: string; desc: string; children: ReactNode }) => (
  <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">{icon}</div>
      <div>
        <h2 className="font-semibold text-slate-950">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-500">{desc}</p>
      </div>
    </div>
    <div className="p-5 sm:p-6">{children}</div>
  </section>
)

const Field = ({ label, hint, children, className = '' }: { label: string; hint?: string; children: ReactNode; className?: string }) => (
  <label className={`block ${className}`}>
    <span className="text-sm font-medium text-slate-700">{label}</span>
    {hint && <span className="ml-2 text-xs text-slate-400">{hint}</span>}
    <div className="mt-1.5">{children}</div>
  </label>
)

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10'

const Toggle = ({ checked, onChange, label, desc }: { checked: boolean; onChange: (value: boolean) => void; label: string; desc: string }) => (
  <button type="button" onClick={() => onChange(!checked)} className={`flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition ${checked ? 'border-blue-200 bg-blue-50/60' : 'border-slate-200 bg-slate-50'}`}>
    <span className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition ${checked ? 'bg-blue-600' : 'bg-slate-300'}`}>
      <span className={`h-4 w-4 rounded-full bg-white shadow transition ${checked ? 'translate-x-4' : ''}`} />
    </span>
    <span>
      <span className="block text-sm font-medium text-slate-800">{label}</span>
      <span className="mt-1 block text-xs leading-5 text-slate-500">{desc}</span>
    </span>
  </button>
)

const Admin = () => {
  const [settings, setSettings] = useState<SettingsState>(defaultSettings)
  const [quota, setQuota] = useState<QuotaConfig>(defaultQuota)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [overview, setOverview] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [savingSettings, setSavingSettings] = useState(false)
  const [savingQuota, setSavingQuota] = useState(false)
  const [resetUsageOnSave, setResetUsageOnSave] = useState(false)

  const regularUsers = useMemo(() => users.filter(item => item.role !== 'admin'), [users])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [settingsData, quotaData, usersData, overviewData] = await Promise.all([
        requestJson('/settings'),
        requestJson('/admin/quota-config'),
        requestJson('/admin/users'),
        requestJson('/admin/overview'),
      ])
      setSettings({
        ...defaultSettings,
        ...settingsData,
        llmProviders: Array.isArray(settingsData.llmProviders) ? settingsData.llmProviders : [],
      })
      setQuota({ ...defaultQuota, ...(quotaData.quota_config || {}) })
      setUsers(usersData.users || [])
      setOverview(overviewData.overview || null)
    } catch (error: any) {
      message.error(error?.message || '管理员数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (authStore.isAdmin) loadAll()
  }, [authStore.user?.id])

  if (!authStore.isAdmin) return <Navigate replace to="/app/Hyper/chat" />

  const updateSetting = (key: keyof SettingsState, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  const updateProvider = (index: number, patch: Partial<LLMProvider>) => {
    setSettings(prev => ({
      ...prev,
      llmProviders: prev.llmProviders.map((provider, providerIndex) => providerIndex === index ? { ...provider, ...patch } : provider),
    }))
  }

  const addProvider = () => {
    setSettings(prev => ({
      ...prev,
      llmProviders: [
        ...prev.llmProviders,
        {
          name: `provider-${prev.llmProviders.length + 1}`,
          baseUrl: prev.baseUrl,
          modelName: prev.modelName,
          apiKeys: [],
          enabled: true,
          maxAsync: Math.max(1, prev.llmPerKeyMaxAsync),
          perKeyMaxAsync: prev.llmPerKeyMaxAsync,
          priority: (prev.llmProviders.length + 1) * 10,
        },
      ],
    }))
  }

  const removeProvider = (index: number) => {
    setSettings(prev => ({ ...prev, llmProviders: prev.llmProviders.filter((_, providerIndex) => providerIndex !== index) }))
  }

  const saveSettings = async () => {
    setSavingSettings(true)
    try {
      await requestJson('/settings', { method: 'POST', body: JSON.stringify(settings) })
      message.success('全站 API 与工具配置已保存')
      await loadAll()
    } catch (error: any) {
      message.error(error?.message || '配置保存失败')
    } finally {
      setSavingSettings(false)
    }
  }

  const saveQuota = async () => {
    setSavingQuota(true)
    try {
      const result = await requestJson('/admin/quota-config', {
        method: 'POST',
        body: JSON.stringify({ ...quota, reset_usage: resetUsageOnSave }),
      })
      message.success(resetUsageOnSave ? `每日额度已保存，并重置 ${result.reset_users || 0} 位用户用量` : '每日公开额度已保存')
      setResetUsageOnSave(false)
      await loadAll()
    } catch (error: any) {
      message.error(error?.message || '额度保存失败')
    } finally {
      setSavingQuota(false)
    }
  }

  const resetUserQuota = async (userId: string) => {
    try {
      await requestJson(`/admin/users/${userId}/quota/reset`, { method: 'POST' })
      message.success('该用户今日用量已重置')
      await loadAll()
    } catch (error: any) {
      message.error(error?.message || '重置失败')
    }
  }

  const resetAllQuotas = async () => {
    try {
      const result = await requestJson('/admin/quotas/reset', { method: 'POST' })
      message.success(`已重置 ${result.reset_users || 0} 位用户的今日用量`)
      await loadAll()
    } catch (error: any) {
      message.error(error?.message || '批量重置失败')
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex flex-col justify-between gap-4 rounded-2xl bg-slate-950 p-6 text-white shadow-xl shadow-slate-300/40 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-blue-300"><ShieldCheck className="h-4 w-4" /> Administrator only</div>
            <h1 className="mt-2 text-2xl font-semibold">全站管理后台</h1>
            <p className="mt-2 text-sm leading-6 text-slate-300">统一管理平台 API、模型池、MinerU 文档转换、每日免费额度和用户用量。</p>
          </div>
          <div className="flex gap-2">
            <button onClick={loadAll} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-4 py-2.5 text-sm font-medium transition hover:bg-white/10 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 刷新</button>
            <button onClick={saveSettings} disabled={savingSettings} className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-slate-100 disabled:opacity-50"><Save className="h-4 w-4" /> {savingSettings ? '保存中…' : '保存 API 配置'}</button>
          </div>
        </div>

        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[
            { label: '全部用户', value: overview?.users_total ?? users.length, icon: <Users className="h-5 w-5" />, color: 'text-blue-700 bg-blue-50' },
            { label: '普通用户', value: overview?.regular_users ?? regularUsers.length, icon: <Users className="h-5 w-5" />, color: 'text-blue-700 bg-blue-50' },
            { label: 'LLM 每日额度', value: quota.trial_llm_calls_limit, icon: <BrainCircuit className="h-5 w-5" />, color: 'text-violet-700 bg-violet-50' },
            { label: 'Embedding 每日额度', value: quota.trial_embedding_calls_limit, icon: <Database className="h-5 w-5" />, color: 'text-amber-700 bg-amber-50' },
          ].map(card => (
            <div key={card.label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${card.color}`}>{card.icon}</div>
              <div className="mt-4 text-2xl font-semibold text-slate-950">{card.value}</div>
              <div className="mt-1 text-sm text-slate-500">{card.label}</div>
            </div>
          ))}
        </div>

        <div className="space-y-6">
          <Section icon={<Server className="h-5 w-5" />} title="基础 LLM 调用配置" desc="兼容旧版单 Provider 调用，也作为多 Provider 未填写字段时的回退值。">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <Field label="Provider 类型"><input className={inputClass} value={settings.modelProvider} onChange={e => updateSetting('modelProvider', e.target.value)} placeholder="openai" /></Field>
              <Field label="API Base URL"><input className={inputClass} value={settings.baseUrl} onChange={e => updateSetting('baseUrl', e.target.value)} placeholder="https://api.openai.com/v1" /></Field>
              <Field label="模型名称"><input className={inputClass} value={settings.modelName} onChange={e => updateSetting('modelName', e.target.value)} placeholder="gpt-5-mini" /></Field>
              <Field label="最大输出 Token"><input className={inputClass} type="number" min={1} value={settings.maxTokens} onChange={e => updateSetting('maxTokens', Number(e.target.value))} /></Field>
              <Field label="Temperature"><input className={inputClass} type="number" min={0} max={2} step={0.1} value={settings.temperature} onChange={e => updateSetting('temperature', Number(e.target.value))} /></Field>
              <Field label="Legacy API Keys" hint="每行一个；*** 表示保留原密钥" className="md:col-span-2 xl:col-span-1"><textarea className={`${inputClass} min-h-24 resize-y font-mono`} value={settings.apiKey} onChange={e => updateSetting('apiKey', e.target.value)} placeholder="sk-..." /></Field>
            </div>
          </Section>

          <Section icon={<Activity className="h-5 w-5" />} title="并发、重试与故障回退" desc="这些字段直接对应后端 LLM Provider Pool 的候选选择、并发槽位、超时与冷却逻辑。">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="请求超时（秒）"><input className={inputClass} type="number" min={1} value={settings.llmTimeout} onChange={e => updateSetting('llmTimeout', Number(e.target.value))} /></Field>
              <Field label="全局最大并发"><input className={inputClass} type="number" min={1} value={settings.llmGlobalMaxAsync} onChange={e => updateSetting('llmGlobalMaxAsync', Number(e.target.value))} /></Field>
              <Field label="模型最大并发（兼容）"><input className={inputClass} type="number" min={1} value={settings.llmModelMaxAsync} onChange={e => updateSetting('llmModelMaxAsync', Number(e.target.value))} /></Field>
              <Field label="每 Key 最大并发"><input className={inputClass} type="number" min={1} value={settings.llmPerKeyMaxAsync} onChange={e => updateSetting('llmPerKeyMaxAsync', Number(e.target.value))} /></Field>
              <Field label="最大重试次数"><input className={inputClass} type="number" min={0} value={settings.llmMaxRetries} onChange={e => updateSetting('llmMaxRetries', Number(e.target.value))} /></Field>
              <Field label="故障 Key 冷却（秒）"><input className={inputClass} type="number" min={1} value={settings.llmKeyCooldownSeconds} onChange={e => updateSetting('llmKeyCooldownSeconds', Number(e.target.value))} /></Field>
              <Field label="Provider 策略" className="sm:col-span-2"><select className={inputClass} value={settings.llmProviderStrategy} onChange={e => updateSetting('llmProviderStrategy', e.target.value)}><option value="priority_round_robin">priority_round_robin</option><option value="round_robin">round_robin</option></select></Field>
            </div>
          </Section>

          <Section icon={<KeyRound className="h-5 w-5" />} title="LLM Provider 池" desc="每个 Provider 都可独立配置 URL、模型、多个 API Key、优先级与并发；请求失败时后端会继续尝试其他可用候选。">
            <div className="space-y-4">
              {settings.llmProviders.map((provider, index) => (
                <div key={`${provider.name}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 sm:p-5">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className={`h-2.5 w-2.5 rounded-full ${provider.enabled ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                      <span className="text-sm font-semibold text-slate-800">Provider {index + 1}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={() => updateProvider(index, { enabled: !provider.enabled })} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${provider.enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'}`}>{provider.enabled ? '已启用' : '已停用'}</button>
                      <button type="button" onClick={() => removeProvider(index)} className="rounded-lg p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600" title="删除 Provider"><Trash2 className="h-4 w-4" /></button>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                    <Field label="名称"><input className={inputClass} value={provider.name} onChange={e => updateProvider(index, { name: e.target.value })} /></Field>
                    <Field label="Base URL"><input className={inputClass} value={provider.baseUrl} onChange={e => updateProvider(index, { baseUrl: e.target.value })} /></Field>
                    <Field label="模型名称"><input className={inputClass} value={provider.modelName} onChange={e => updateProvider(index, { modelName: e.target.value })} /></Field>
                    <Field label="优先级" hint="越小越优先"><input className={inputClass} type="number" min={0} value={provider.priority} onChange={e => updateProvider(index, { priority: Number(e.target.value) })} /></Field>
                    <Field label="Provider 最大并发"><input className={inputClass} type="number" min={1} value={provider.maxAsync} onChange={e => updateProvider(index, { maxAsync: Number(e.target.value) })} /></Field>
                    <Field label="每 Key 最大并发"><input className={inputClass} type="number" min={1} value={provider.perKeyMaxAsync ?? settings.llmPerKeyMaxAsync} onChange={e => updateProvider(index, { perKeyMaxAsync: Number(e.target.value) })} /></Field>
                    <Field label="API Keys" hint="每行一个；*** 保留原值" className="md:col-span-2"><textarea className={`${inputClass} min-h-24 resize-y font-mono`} value={(provider.apiKeys || []).join('\n')} onChange={e => updateProvider(index, { apiKeys: e.target.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean) })} placeholder="sk-..." /></Field>
                  </div>
                </div>
              ))}
              {settings.llmProviders.length === 0 && <div className="rounded-xl border border-dashed border-slate-300 px-5 py-8 text-center text-sm text-slate-500">当前使用上方 Legacy 单 Provider 配置。添加 Provider 后将启用多 Provider 池。</div>}
              <button type="button" onClick={addProvider} className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-medium text-blue-800 transition hover:bg-blue-100"><Plus className="h-4 w-4" /> 添加 Provider</button>
            </div>
          </Section>

          <Section icon={<Database className="h-5 w-5" />} title="Embedding 调用配置" desc="Embedding 调用使用独立 URL、模型、维度与多 Key 轮换；未填写时按后端逻辑回退到 LLM Base URL / API Key。">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="Embedding Base URL" className="xl:col-span-2"><input className={inputClass} value={settings.embeddingBaseUrl} onChange={e => updateSetting('embeddingBaseUrl', e.target.value)} placeholder="留空则回退到 LLM Base URL" /></Field>
              <Field label="Embedding 模型"><input className={inputClass} value={settings.embeddingModel} onChange={e => updateSetting('embeddingModel', e.target.value)} /></Field>
              <Field label="向量维度"><input className={inputClass} type="number" min={1} value={settings.embeddingDim} onChange={e => updateSetting('embeddingDim', Number(e.target.value))} /></Field>
              <Field label="Embedding API Keys" hint="每行一个；支持轮换" className="md:col-span-2 xl:col-span-4"><textarea className={`${inputClass} min-h-24 resize-y font-mono`} value={settings.embeddingApiKey} onChange={e => updateSetting('embeddingApiKey', e.target.value)} placeholder="留空则回退到 Legacy LLM API Key" /></Field>
            </div>
          </Section>

          <Section icon={<Database className="h-5 w-5" />} title="MinerU 文档转换" desc="配置全站 MinerU 文档解析服务。Token 仅保存在后端，普通用户只能查看可用状态与转换能力。">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="API Base URL" hint="包含 /api/v4" className="xl:col-span-2"><input className={inputClass} value={settings.mineruApiBaseUrl} onChange={e => updateSetting('mineruApiBaseUrl', e.target.value)} placeholder="https://mineru.net/api/v4" /></Field>
              <Field label="API Token" hint="*** 表示保留已有值" className="xl:col-span-2"><input className={inputClass} type="password" value={settings.mineruApiToken} onChange={e => updateSetting('mineruApiToken', e.target.value)} placeholder="填写 MinerU API Token" /></Field>
              <Field label="模型版本"><select className={inputClass} value={settings.mineruModelVersion} onChange={e => updateSetting('mineruModelVersion', e.target.value)}><option value="pipeline">pipeline</option><option value="vlm">vlm</option></select></Field>
              <Field label="文档语言" hint="例如 ch / en"><input className={inputClass} value={settings.mineruLanguage} onChange={e => updateSetting('mineruLanguage', e.target.value)} placeholder="ch" /></Field>
              <Field label="额外导出格式" hint="逗号分隔"><input className={inputClass} value={(settings.mineruExtraFormats || []).join(', ')} onChange={e => updateSetting('mineruExtraFormats', e.target.value.split(',').map(v => v.trim()).filter(Boolean))} placeholder="docx, html" /></Field>
              <Field label="轮询间隔（秒）"><input className={inputClass} type="number" min={1} max={30} value={settings.mineruPollIntervalSeconds} onChange={e => updateSetting('mineruPollIntervalSeconds', Number(e.target.value))} /></Field>
              <Field label="最大轮询次数"><input className={inputClass} type="number" min={1} max={1000} value={settings.mineruMaxPollAttempts} onChange={e => updateSetting('mineruMaxPollAttempts', Number(e.target.value))} /></Field>
              <Field label="上传文件上限（MB）"><input className={inputClass} type="number" min={1} max={200} value={settings.mineruMaxFileMb} onChange={e => updateSetting('mineruMaxFileMb', Number(e.target.value))} /></Field>
              <Field label="结果 ZIP 上限（MB）"><input className={inputClass} type="number" min={1} max={1000} value={settings.mineruMaxResultMb} onChange={e => updateSetting('mineruMaxResultMb', Number(e.target.value))} /></Field>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <Toggle checked={settings.mineruEnableOcr} onChange={value => updateSetting('mineruEnableOcr', value)} label="OCR 识别" desc="扫描件和图片文档启用文字识别" />
              <Toggle checked={settings.mineruEnableFormula} onChange={value => updateSetting('mineruEnableFormula', value)} label="公式识别" desc="提取并保留文档中的数学公式" />
              <Toggle checked={settings.mineruEnableTable} onChange={value => updateSetting('mineruEnableTable', value)} label="表格识别" desc="识别表格结构并转换为 Markdown" />
            </div>
          </Section>

          <Section icon={<Gauge className="h-5 w-5" />} title="每日公开免费额度" desc="普通用户未配置个人 API 时消耗平台额度；每日在 UTC 00:00 自动清零。管理员账号不受额度限制。">
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="每日文档入库数"><input className={inputClass} type="number" min={0} value={quota.trial_docs_limit} onChange={e => setQuota(prev => ({ ...prev, trial_docs_limit: Number(e.target.value) }))} /></Field>
              <Field label="每日 LLM 调用数"><input className={inputClass} type="number" min={0} value={quota.trial_llm_calls_limit} onChange={e => setQuota(prev => ({ ...prev, trial_llm_calls_limit: Number(e.target.value) }))} /></Field>
              <Field label="每日 Embedding 调用数"><input className={inputClass} type="number" min={0} value={quota.trial_embedding_calls_limit} onChange={e => setQuota(prev => ({ ...prev, trial_embedding_calls_limit: Number(e.target.value) }))} /></Field>
            </div>
            <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-sm text-amber-900">
              <input type="checkbox" className="mt-1" checked={resetUsageOnSave} onChange={e => setResetUsageOnSave(e.target.checked)} />
              <span><span className="font-medium">保存后立即重置所有普通用户今日用量</span><span className="mt-1 block text-xs leading-5 text-amber-700">修改额度上限通常不需要勾选；需要让新额度立刻完整生效时再勾选。</span></span>
            </label>
            <div className="mt-4 flex flex-wrap gap-3">
              <button onClick={saveQuota} disabled={savingQuota} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50"><Save className="h-4 w-4" /> {savingQuota ? '保存中…' : '保存每日额度'}</button>
              <button onClick={resetAllQuotas} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"><RotateCcw className="h-4 w-4" /> 立即重置全部今日用量</button>
            </div>
          </Section>

          <Section icon={<Users className="h-5 w-5" />} title="用户与用量" desc="查看所有账号的今日平台额度消耗，并可单独重置普通用户用量。">
            <div className="overflow-x-auto rounded-xl border border-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr><th className="px-4 py-3">用户</th><th className="px-4 py-3">角色</th><th className="px-4 py-3">文档</th><th className="px-4 py-3">LLM</th><th className="px-4 py-3">Embedding</th><th className="px-4 py-3">下次重置</th><th className="px-4 py-3 text-right">操作</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {users.map(item => (
                    <tr key={item.id} className="text-slate-700">
                      <td className="px-4 py-3"><div className="font-medium text-slate-900">{item.display_name || item.email}</div><div className="mt-0.5 text-xs text-slate-400">{item.email}</div></td>
                      <td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${item.role === 'admin' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-600'}`}>{item.role === 'admin' ? '管理员' : '用户'}</span></td>
                      <td className="px-4 py-3">{item.quota.unlimited ? '不限' : `${item.quota.trial_docs_used}/${item.quota.trial_docs_limit}`}</td>
                      <td className="px-4 py-3">{item.quota.unlimited ? '不限' : `${item.quota.trial_llm_calls_used}/${item.quota.trial_llm_calls_limit}`}</td>
                      <td className="px-4 py-3">{item.quota.unlimited ? '不限' : `${item.quota.trial_embedding_calls_used}/${item.quota.trial_embedding_calls_limit}`}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{item.quota.daily_reset_at ? new Date(item.quota.daily_reset_at).toLocaleString() : '—'}</td>
                      <td className="px-4 py-3 text-right"><button disabled={item.role === 'admin'} onClick={() => resetUserQuota(item.id)} className="rounded-lg px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-slate-300">重置用量</button></td>
                    </tr>
                  ))}
                  {!users.length && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-400">{loading ? '正在加载…' : '暂无用户'}</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>
        </div>
      </div>
    </div>
  )
}

export default observer(Admin)
