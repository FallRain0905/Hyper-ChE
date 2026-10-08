import { useCallback, useEffect, useMemo, useState } from 'react'
import { observer } from 'mobx-react'
import { message } from 'antd'
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Cpu,
  Database,
  Gauge,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Sparkles,
  Trash2,
  Zap,
} from 'lucide-react'
import { authStore } from '@/store/auth'
import { SERVER_URL } from '@/utils'

type ModelRole = 'extraction' | 'answer' | 'judge' | 'embedding' | 'reranker'

type ChannelModel = {
  id?: string
  role: ModelRole
  model_name: string
  embedding_dim?: number | null
  context_window?: number | null
  max_concurrency: number
  per_key_max_concurrency?: number | null
  timeout_seconds: number
  priority: number
  enabled: boolean
}

type Channel = {
  id: string
  scope: 'platform' | 'user'
  owner_user_id?: string | null
  provider_name: string
  protocol: string
  base_url: string
  status: string
  has_secret: boolean
  secret?: string
  migrated_from?: string | null
  models: ChannelModel[]
}

type RoleSummary = {
  role: string
  count: number
  providers: Array<{
    model_name: string
    embedding_dim?: number | null
    provider_name: string
    scope: string
    base_url: string
    has_secret: boolean
    priority: number
  }>
}

const ROLE_META: Record<ModelRole, { label: string; desc: string; icon: any; color: string }> = {
  extraction: { label: '抽取 Extraction', desc: '建库时抽取实体、关系与超边', icon: Sparkles, color: 'text-violet-700 bg-violet-50' },
  answer: { label: '回答 Answer', desc: '问答时生成最终回答', icon: BrainCircuit, color: 'text-blue-700 bg-blue-50' },
  judge: { label: '评审 Judge', desc: '预留：答案质量判定', icon: Gauge, color: 'text-amber-700 bg-amber-50' },
  embedding: { label: '向量 Embedding', desc: '文本向量化，维度必须与知识库一致', icon: Database, color: 'text-emerald-700 bg-emerald-50' },
  reranker: { label: '重排 Reranker', desc: '预留：检索结果重排', icon: Cpu, color: 'text-rose-700 bg-rose-50' },
}

const inputClass =
  'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10'
const labelClass = 'text-xs font-medium text-slate-600'

async function requestJson(path: string, init?: RequestInit) {
  const response = await fetch(`${SERVER_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data?.success === false) {
    throw new Error(data?.detail || data?.message || `请求失败（${response.status}）`)
  }
  return data
}

const emptyModel = (role: ModelRole = 'answer'): ChannelModel => ({
  role,
  model_name: '',
  embedding_dim: role === 'embedding' ? 2560 : null,
  max_concurrency: 4,
  timeout_seconds: 600,
  priority: 100,
  enabled: true,
})

const Providers = () => {
  const isAdmin = authStore.isAdmin
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [platform, setPlatform] = useState<Channel[]>([])
  const [userChannels, setUserChannels] = useState<Channel[]>([])
  const [roles, setRoles] = useState<Record<string, RoleSummary>>({})
  const [embeddingDim, setEmbeddingDim] = useState<number | null>(null)
  const [health, setHealth] = useState<any>(null)

  const [draft, setDraft] = useState<Channel | null>(null)
  const [draftIsNew, setDraftIsNew] = useState(false)
  const [editScope, setEditScope] = useState<'platform' | 'user'>('user')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [listData, statusData] = await Promise.all([
        requestJson('/providers'),
        requestJson('/providers/status'),
      ])
      setPlatform(listData.platform || [])
      setUserChannels(listData.user || [])
      setRoles(statusData.roles || {})
      setEmbeddingDim(statusData.embedding_dim ?? null)
      setHealth(statusData.health || null)
    } catch (error: any) {
      message.error(error?.message || '加载渠道配置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const startNew = (scope: 'platform' | 'user') => {
    setEditScope(scope)
    setDraftIsNew(true)
    setDraft({
      id: '',
      scope,
      provider_name: '',
      protocol: 'openai',
      base_url: '',
      status: 'active',
      has_secret: false,
      secret: '',
      models: [emptyModel('answer'), emptyModel('embedding')],
    })
  }

  const startEdit = (channel: Channel) => {
    setEditScope(channel.scope)
    setDraftIsNew(false)
    setDraft({ ...channel, secret: '', models: channel.models.map(m => ({ ...m })) })
  }

  const updateDraft = (patch: Partial<Channel>) => setDraft(prev => (prev ? { ...prev, ...patch } : prev))

  const updateModel = (index: number, patch: Partial<ChannelModel>) =>
    setDraft(prev => {
      if (!prev) return prev
      const models = prev.models.map((model, i) => (i === index ? { ...model, ...patch } : model))
      return { ...prev, models }
    })

  const addModel = () => setDraft(prev => (prev ? { ...prev, models: [...prev.models, emptyModel('answer')] } : prev))

  const removeModel = (index: number) =>
    setDraft(prev => (prev ? { ...prev, models: prev.models.filter((_, i) => i !== index) } : prev))

  const save = async () => {
    if (!draft) return
    if (!draft.provider_name.trim()) return message.warning('请填写渠道名称')
    if (!draft.base_url.trim()) return message.warning('请填写 Base URL')
    if (draftIsNew && !draft.secret.trim()) return message.warning('新建渠道必须填写 API Key')
    const invalid = draft.models.find(model => !model.model_name.trim())
    if (invalid) return message.warning('每个模型都需要填写模型名称')

    setSaving(true)
    try {
      const payload = {
        scope: draft.scope,
        provider_name: draft.provider_name,
        protocol: draft.protocol,
        base_url: draft.base_url,
        status: draft.status,
        // Empty string keeps the stored secret; the UI never echoes it back.
        secret: draft.secret || '',
        models: draft.models.map(model => ({
          role: model.role,
          model_name: model.model_name,
          embedding_dim: model.role === 'embedding' ? model.embedding_dim ?? null : null,
          max_concurrency: model.max_concurrency,
          per_key_max_concurrency: model.per_key_max_concurrency ?? null,
          timeout_seconds: model.timeout_seconds,
          priority: model.priority,
          enabled: model.enabled,
        })),
      }
      if (draftIsNew) {
        await requestJson('/providers', { method: 'POST', body: JSON.stringify(payload) })
        message.success('渠道已创建')
      } else {
        await requestJson(`/providers/${draft.id}`, { method: 'PUT', body: JSON.stringify(payload) })
        message.success('渠道已更新')
      }
      setDraft(null)
      await load()
    } catch (error: any) {
      message.error(error?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const removeChannel = async (channel: Channel) => {
    try {
      await requestJson(`/providers/${channel.id}`, { method: 'DELETE' })
      message.success('渠道已删除')
      if (draft?.id === channel.id) setDraft(null)
      await load()
    } catch (error: any) {
      message.error(error?.message || '删除失败')
    }
  }

  const resetHealth = async () => {
    try {
      await requestJson('/llm-provider-pool/reset', { method: 'POST' })
      message.success('渠道健康状态已重置')
      await load()
    } catch (error: any) {
      message.error(error?.message || '重置失败')
    }
  }

  const missingRoles = useMemo(
    () => (['extraction', 'answer', 'embedding'] as ModelRole[]).filter(role => !(roles[role]?.count > 0)),
    [roles],
  )

  const renderChannelCard = (channel: Channel) => (
    <div key={channel.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${channel.status === 'active' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
            <span className="font-medium text-slate-900">{channel.provider_name}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{channel.protocol}</span>
            {channel.scope === 'user' && (
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">个人</span>
            )}
            {channel.migrated_from && (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">迁移自 {channel.migrated_from}</span>
            )}
          </div>
          <div className="mt-2 truncate text-xs text-slate-500">{channel.base_url}</div>
          <div className="mt-1 flex items-center gap-3 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1">
              <KeyRound className="h-3 w-3" />
              {channel.has_secret ? '密钥已配置' : '未配置密钥'}
            </span>
            <span>{channel.models.length} 个模型</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <button onClick={() => startEdit(channel)} className="rounded-lg px-3 py-1.5 text-xs font-medium text-blue-700 transition hover:bg-blue-50">
            编辑
          </button>
          <button onClick={() => removeChannel(channel)} className="rounded-lg p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {channel.models.map(model => {
          const meta = ROLE_META[model.role] || ROLE_META.answer
          return (
            <span key={model.id || `${model.role}-${model.model_name}`} className={`rounded-lg px-2 py-1 text-[11px] font-medium ${meta.color}`}>
              {meta.label.split(' ')[0]} · {model.model_name}
              {model.role === 'embedding' && model.embedding_dim ? ` · ${model.embedding_dim}d` : ''}
            </span>
          )
        })}
      </div>
    </div>
  )

  return (
    <div className="relative min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="hyperche-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="relative mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
              <Server className="h-3.5 w-3.5" /> Unified API Channels
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">API 渠道与模型</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              统一管理 API 渠道、密钥、LLM 与 Embedding 模型。密钥仅保存在后端并加密存储，前端永远只看到渠道名称、模型名称与状态。
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} 刷新
            </button>
            {isAdmin && (
              <button onClick={() => startNew('platform')} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800">
                <Plus className="h-4 w-4" /> 平台渠道
              </button>
            )}
            <button onClick={() => startNew('user')} className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-800 transition hover:bg-blue-100">
              <Plus className="h-4 w-4" /> 我的渠道
            </button>
          </div>
        </header>

        {missingRoles.length > 0 && (
          <div className="mb-5 flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <span className="font-medium">缺少必要模型角色：</span>
              {missingRoles.map(role => ROLE_META[role].label).join('、')}
              。建库与问答需要 extraction、answer 和 embedding 三类模型。
            </div>
          </div>
        )}

        {/* Role readiness */}
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {(Object.keys(ROLE_META) as ModelRole[]).map(role => {
            const meta = ROLE_META[role]
            const summary = roles[role]
            const Icon = meta.icon
            const ready = (summary?.count || 0) > 0
            return (
              <div key={role} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${meta.color}`}>
                    <Icon className="h-4.5 w-4.5" />
                  </div>
                  {ready ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  ) : (
                    <span className="text-[11px] font-medium text-slate-400">未配置</span>
                  )}
                </div>
                <div className="mt-3 text-sm font-semibold text-slate-900">{meta.label}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{meta.desc}</div>
                <div className="mt-2 text-xs font-medium text-slate-400">{summary?.count || 0} 个模型</div>
              </div>
            )
          })}
        </div>

        {/* Embedding dimension + pool health */}
        <div className="mb-6 grid gap-4 lg:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Database className="h-4 w-4 text-emerald-600" /> Embedding 维度
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              维度写入模型配置，并在加载向量库时校验。当前生效维度与知识库不一致时会直接报错，而不是静默返回错误结果。
            </p>
            <div className="mt-3 flex items-center gap-3">
              <span className="rounded-xl bg-slate-950 px-3 py-1.5 font-mono text-sm text-white">
                {embeddingDim ? `${embeddingDim} dim` : '未设置'}
              </span>
              <span className="text-xs text-slate-500">
                {roles.embedding?.providers?.[0]?.model_name || '尚未配置 Embedding 模型'}
              </span>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Activity className="h-4 w-4 text-blue-600" /> 渠道健康
              </div>
              <button onClick={resetHealth} className="rounded-lg px-2.5 py-1 text-xs font-medium text-blue-700 transition hover:bg-blue-50">
                重置
              </button>
            </div>
            <div className="mt-3 space-y-1.5 text-xs text-slate-600">
              <div className="flex justify-between"><span>追踪密钥</span><span className="font-medium text-slate-900">{health?.tracked_keys ?? 0}</span></div>
              <div className="flex justify-between"><span>已禁用</span><span className="font-medium text-rose-600">{health?.disabled_keys ?? 0}</span></div>
              <div className="flex justify-between"><span>轮询游标</span><span className="font-medium text-slate-900">{health?.cursor ?? 0}</span></div>
            </div>
          </div>
        </div>

        {/* Editor */}
        {draft && (
          <section className="mb-6 rounded-3xl border border-blue-200 bg-white/95 p-5 shadow-sm backdrop-blur sm:p-6">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-slate-950">
                  {draftIsNew ? '新建渠道' : `编辑渠道 · ${draft.provider_name}`}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {draft.scope === 'platform' ? '平台渠道对所有普通用户可见，并消耗平台免费额度。' : '个人渠道仅你自己可用，优先于平台渠道。'}
                </p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setDraft(null)} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50">
                  取消
                </button>
                <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
                </button>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <label className="block">
                <span className={labelClass}>渠道名称</span>
                <input className={`${inputClass} mt-1.5`} value={draft.provider_name} onChange={e => updateDraft({ provider_name: e.target.value })} placeholder="siliconflow-primary" />
              </label>
              <label className="block">
                <span className={labelClass}>协议</span>
                <select className={`${inputClass} mt-1.5`} value={draft.protocol} onChange={e => updateDraft({ protocol: e.target.value })}>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                </select>
              </label>
              <label className="block md:col-span-2">
                <span className={labelClass}>Base URL</span>
                <input className={`${inputClass} mt-1.5`} value={draft.base_url} onChange={e => updateDraft({ base_url: e.target.value })} placeholder="https://api.siliconflow.cn/v1" />
              </label>
              <label className="block md:col-span-2">
                <span className={labelClass}>
                  API Key {draftIsNew ? '' : '（留空或保持 *** 表示不修改）'}
                </span>
                <input
                  className={`${inputClass} mt-1.5 font-mono`}
                  type="password"
                  value={draft.secret || ''}
                  onChange={e => updateDraft({ secret: e.target.value })}
                  placeholder={draft.has_secret && !draftIsNew ? '*** 已配置，留空保持不变' : 'sk-...'}
                />
              </label>
              <label className="block">
                <span className={labelClass}>状态</span>
                <select className={`${inputClass} mt-1.5`} value={draft.status} onChange={e => updateDraft({ status: e.target.value })}>
                  <option value="active">启用</option>
                  <option value="disabled">停用</option>
                </select>
              </label>
            </div>

            <div className="mt-6">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-800">模型配置</h3>
                <button onClick={addModel} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50">
                  <Plus className="h-3.5 w-3.5" /> 添加模型
                </button>
              </div>
              <div className="space-y-3">
                {draft.models.map((model, index) => (
                  <div key={index} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <label className="block">
                        <span className={labelClass}>模型角色</span>
                        <select
                          className={`${inputClass} mt-1.5`}
                          value={model.role}
                          onChange={e => updateModel(index, { role: e.target.value as ModelRole })}
                        >
                          {(Object.keys(ROLE_META) as ModelRole[]).map(role => (
                            <option key={role} value={role}>{ROLE_META[role].label}</option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className={labelClass}>模型名称</span>
                        <input className={`${inputClass} mt-1.5`} value={model.model_name} onChange={e => updateModel(index, { model_name: e.target.value })} placeholder="deepseek-v4-flash" />
                      </label>
                      {model.role === 'embedding' && (
                        <label className="block">
                          <span className={labelClass}>向量维度</span>
                          <input
                            className={`${inputClass} mt-1.5`}
                            type="number"
                            min={1}
                            value={model.embedding_dim ?? ''}
                            onChange={e => updateModel(index, { embedding_dim: e.target.value ? Number(e.target.value) : null })}
                            placeholder="2560"
                          />
                        </label>
                      )}
                      <label className="block">
                        <span className={labelClass}>最大并发</span>
                        <input className={`${inputClass} mt-1.5`} type="number" min={1} value={model.max_concurrency} onChange={e => updateModel(index, { max_concurrency: Number(e.target.value) })} />
                      </label>
                      <label className="block">
                        <span className={labelClass}>超时（秒）</span>
                        <input className={`${inputClass} mt-1.5`} type="number" min={1} value={model.timeout_seconds} onChange={e => updateModel(index, { timeout_seconds: Number(e.target.value) })} />
                      </label>
                      <label className="block">
                        <span className={labelClass}>优先级（越小越优先）</span>
                        <input className={`${inputClass} mt-1.5`} type="number" min={0} value={model.priority} onChange={e => updateModel(index, { priority: Number(e.target.value) })} />
                      </label>
                      <div className="flex items-end justify-between gap-2">
                        <button
                          onClick={() => updateModel(index, { enabled: !model.enabled })}
                          className={`rounded-lg px-3 py-1.5 text-xs font-medium ${model.enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'}`}
                        >
                          {model.enabled ? '已启用' : '已停用'}
                        </button>
                        <button onClick={() => removeModel(index)} className="rounded-lg p-2 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
                {draft.models.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-300 px-5 py-6 text-center text-sm text-slate-500">
                    该渠道还没有模型配置，点击「添加模型」开始。
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* Channel lists */}
        <div className="space-y-6">
          <section>
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-violet-600" />
              <h2 className="font-semibold text-slate-900">平台渠道</h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{platform.length}</span>
              {!isAdmin && <span className="text-xs text-slate-400">仅管理员可管理</span>}
            </div>
            {platform.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-10 text-center text-sm text-slate-500">
                {isAdmin ? '暂无平台渠道，点击右上角「平台渠道」创建。' : '暂无平台渠道。'}
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">{platform.map(renderChannelCard)}</div>
            )}
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-blue-600" />
              <h2 className="font-semibold text-slate-900">我的渠道</h2>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{userChannels.length}</span>
            </div>
            {userChannels.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-10 text-center text-sm text-slate-500">
                还没有个人渠道。添加自己的 API Key 后，你的请求会优先使用个人渠道。
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">{userChannels.map(renderChannelCard)}</div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

export default observer(Providers)
