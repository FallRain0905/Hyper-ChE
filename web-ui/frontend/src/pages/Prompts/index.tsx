import { useCallback, useEffect, useMemo, useState } from 'react'
import { observer } from 'mobx-react'
import { message } from 'antd'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Copy,
  Database,
  FileCode2,
  History,
  Info,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { authStore } from '@/store/auth'
import { SERVER_URL } from '@/utils'

type PromptPack = {
  id: string
  domain_id: string
  name: string
  description: string
  scope: 'system' | 'user'
  status: string
  published_version_id?: string | null
  version_count?: number
  updated_at?: string
}

type PromptVersion = {
  id: string
  version_no: number
  status: 'draft' | 'published'
  changelog: string
  created_at?: string
  published_at?: string
  content_hash?: string
}

type VersionBody = { config: Record<string, any>; prompts: Record<string, string> }

type PackDetail = {
  pack: PromptPack
  published: PromptVersion | null
  draft: PromptVersion | null
  editable: VersionBody | null
  versions: PromptVersion[]
  read_only: boolean
}

type Impact = {
  requires_rebuild: boolean
  rebuild_reasons: string[]
  no_rebuild_keys: string[]
  message: string
}

const ALWAYS_REBUILD = ['entity_types', 'relation_types', 'one_pass_extraction', 'critical_rules']
const NO_REBUILD = ['answer', 'judge', 'query_keywords']

const PROMPT_SECTIONS: Array<{ key: string; label: string; hint: string; rebuild: boolean }> = [
  { key: 'one_pass_extraction', label: 'One-pass 抽取', hint: '一次调用同时产出实体、低阶关系与超边', rebuild: true },
  { key: 'entity_extraction', label: '实体抽取', hint: '分阶段路径的实体抽取模板', rebuild: true },
  { key: 'relationship_extraction', label: '关系抽取', hint: '关系/超边抽取模板', rebuild: true },
  { key: 'low_order_extraction', label: '低阶关系', hint: '二阶关系抽取模板', rebuild: true },
  { key: 'high_order_extraction', label: '高阶超边', hint: '高阶超边抽取模板', rebuild: true },
  { key: 'query_keywords', label: 'Query 关键词', hint: '检索前关键词抽取', rebuild: false },
  { key: 'answer', label: '回答 Answer', hint: '生成最终回答的提示词', rebuild: false },
  { key: 'judge', label: '评审 Judge', hint: '预留：答案质量判定提示词', rebuild: false },
]

const inputClass =
  'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10'

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

const PromptStudio = () => {
  const [packs, setPacks] = useState<PromptPack[]>([])
  const [loading, setLoading] = useState(true)
  const [activeId, setActiveId] = useState<string>('')
  const [detail, setDetail] = useState<PackDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [config, setConfig] = useState<Record<string, any>>({})
  const [prompts, setPrompts] = useState<Record<string, string>>({})
  const [activeSection, setActiveSection] = useState<string>('one_pass_extraction')
  const [changelog, setChangelog] = useState('')
  const [impact, setImpact] = useState<Impact | null>(null)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [newDomainId, setNewDomainId] = useState('')
  const [newName, setNewName] = useState('')

  const loadPacks = useCallback(async () => {
    setLoading(true)
    try {
      const data = await requestJson('/prompts')
      setPacks(data.packs || [])
      return data.packs || []
    } catch (error: any) {
      message.error(error?.message || '加载 Prompt 包失败')
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (packId: string) => {
    if (!packId) return
    setDetailLoading(true)
    try {
      const data: PackDetail = await requestJson(`/prompts/${packId}`)
      setDetail(data)
      setConfig(data.editable?.config || {})
      setPrompts(data.editable?.prompts || {})
      setChangelog('')
      setImpact(null)
    } catch (error: any) {
      message.error(error?.message || '加载 Prompt 详情失败')
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPacks().then(list => {
      if (list.length && !activeId) setActiveId(list[0].id)
    })
  }, [loadPacks])

  useEffect(() => {
    if (activeId) loadDetail(activeId)
  }, [activeId])

  const readOnly = detail?.read_only ?? true
  const entityTypes: any[] = useMemo(() => (Array.isArray(config.entity_types) ? config.entity_types : []), [config])
  const relationTypes: any[] = useMemo(() => (Array.isArray(config.relation_types) ? config.relation_types : []), [config])

  const toTypeRows = (rows: any[]): Array<{ name: string; description: string; examples: string }> =>
    rows.map(item =>
      typeof item === 'string'
        ? { name: item, description: '', examples: '' }
        : {
            name: item?.name || '',
            description: item?.description || '',
            examples: Array.isArray(item?.examples) ? item.examples.join(', ') : item?.examples || '',
          },
    )

  const [entityRows, setEntityRows] = useState<Array<{ name: string; description: string; examples: string }>>([])
  const [relationRows, setRelationRows] = useState<Array<{ name: string; description: string; examples: string }>>([])

  useEffect(() => {
    setEntityRows(toTypeRows(entityTypes))
    setRelationRows(toTypeRows(relationTypes))
  }, [config])

  const rowsToConfig = (
    rows: Array<{ name: string; description: string; examples: string }>,
    base: any[],
  ): any[] =>
    rows
      .filter(row => row.name.trim())
      .map(row => {
        const original = base.find(item => (typeof item === 'string' ? item : item?.name) === row.name)
        const shaped = typeof original === 'object' && original !== null ? { ...original } : {}
        shaped.name = row.name.trim()
        if (row.description) shaped.description = row.description
        if (row.examples) shaped.examples = row.examples.split(',').map(s => s.trim()).filter(Boolean)
        return shaped
      })

  const buildPayload = () => ({
    config: {
      ...config,
      entity_types: rowsToConfig(entityRows, entityTypes),
      relation_types: rowsToConfig(relationRows, relationTypes),
    },
    prompts: Object.fromEntries(Object.entries(prompts).filter(([, value]) => value !== undefined)),
    changelog,
  })

  const saveDraft = async () => {
    if (!detail) return
    setSaving(true)
    try {
      const data = await requestJson(`/prompts/${detail.pack.id}`, {
        method: 'PUT',
        body: JSON.stringify(buildPayload()),
      })
      setImpact(data.impact)
      message.success('草稿已保存')
      await loadDetail(detail.pack.id)
    } catch (error: any) {
      message.error(error?.message || '保存草稿失败')
    } finally {
      setSaving(false)
    }
  }

  const publish = async () => {
    if (!detail) return
    setPublishing(true)
    try {
      await requestJson(`/prompts/${detail.pack.id}/publish`, {
        method: 'POST',
        body: JSON.stringify(buildPayload()),
      })
      message.success('已发布新版本')
      await Promise.all([loadDetail(detail.pack.id), loadPacks()])
    } catch (error: any) {
      message.error(error?.message || '发布失败')
    } finally {
      setPublishing(false)
    }
  }

  const rollback = async (versionId: string) => {
    if (!detail) return
    try {
      await requestJson(`/prompts/${detail.pack.id}/rollback/${versionId}`, { method: 'POST' })
      message.success('已回滚为新的草稿版本')
      await loadDetail(detail.pack.id)
    } catch (error: any) {
      message.error(error?.message || '回滚失败')
    }
  }

  const createPack = async () => {
    if (!newDomainId.trim()) return message.warning('请填写 domain_id')
    try {
      const data = await requestJson('/prompts', {
        method: 'POST',
        body: JSON.stringify({ domain_id: newDomainId.trim(), name: newName.trim() || newDomainId.trim(), scope: 'user' }),
      })
      message.success('Prompt 包已创建')
      setCreateOpen(false)
      setNewDomainId('')
      setNewName('')
      await loadPacks()
      setActiveId(data.pack.id)
    } catch (error: any) {
      message.error(error?.message || '创建失败')
    }
  }

  const deletePack = async (pack: PromptPack) => {
    if (pack.scope === 'system') return
    try {
      await requestJson(`/prompts/${pack.id}`, { method: 'DELETE' })
      message.success('Prompt 包已删除')
      const list = await loadPacks()
      setActiveId(list[0]?.id || '')
    } catch (error: any) {
      message.error(error?.message || '删除失败')
    }
  }

  const activeSectionMeta = PROMPT_SECTIONS.find(s => s.key === activeSection) || PROMPT_SECTIONS[0]
  const willAffectRebuild =
    activeSectionMeta.rebuild && (prompts[activeSection] || '').length > 0

  return (
    <div className="relative min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="hyperche-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="relative mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-violet-100 bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">
              <FileCode2 className="h-3.5 w-3.5" /> Prompt Studio
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-950">领域提示词管理</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              管理领域实体类型、关系类型与各阶段提示词。支持草稿、发布与回滚，每次建库与问答都会绑定具体的 prompt 版本。
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => loadPacks()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} 刷新
            </button>
            <button onClick={() => setCreateOpen(true)} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800">
              <Plus className="h-4 w-4" /> 新建 Prompt 包
            </button>
          </div>
        </header>

        {/* Create form */}
        {createOpen && (
          <section className="mb-6 rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
            <div className="grid gap-4 md:grid-cols-3">
              <label className="block">
                <span className="text-xs font-medium text-slate-600">domain_id（可复用内置领域作为模板）</span>
                <input className={`${inputClass} mt-1.5`} value={newDomainId} onChange={e => setNewDomainId(e.target.value)} placeholder="flow_battery" />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-slate-600">显示名称</span>
                <input className={`${inputClass} mt-1.5`} value={newName} onChange={e => setNewName(e.target.value)} placeholder="我的液流电池提示词" />
              </label>
              <div className="flex items-end gap-2">
                <button onClick={createPack} className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800">创建</button>
                <button onClick={() => setCreateOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm text-slate-600 transition hover:bg-slate-50">取消</button>
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              填写内置领域名（如 flow_battery）会自动复制其配置与提示词作为起点。
            </p>
          </section>
        )}

        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)_290px]">
          {/* Pack list */}
          <aside className="rounded-3xl border border-slate-200 bg-white/85 p-3 shadow-sm backdrop-blur">
            <div className="px-2 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              提示词包
            </div>
            <div className="space-y-1">
              {packs.map(pack => (
                <button
                  key={pack.id}
                  onClick={() => setActiveId(pack.id)}
                  className={`group flex w-full items-start gap-2 rounded-xl px-3 py-2.5 text-left transition ${
                    activeId === pack.id ? 'bg-violet-50 ring-1 ring-violet-100' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-slate-900">{pack.name}</span>
                      {pack.scope === 'system' ? (
                        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">内置</span>
                      ) : (
                        <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">我的</span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-slate-400">{pack.domain_id}</div>
                    <div className="mt-1 flex items-center gap-2 text-[11px]">
                      <span className={`${pack.status === 'published' ? 'text-emerald-600' : 'text-amber-600'}`}>
                        {pack.status === 'published' ? '已发布' : '草稿'}
                      </span>
                      <span className="text-slate-400">{pack.version_count || 0} 个版本</span>
                    </div>
                  </div>
                  {pack.scope === 'user' && (
                    <span
                      onClick={e => { e.stopPropagation(); deletePack(pack) }}
                      className="mt-0.5 shrink-0 rounded p-1 text-slate-300 opacity-0 transition group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-500"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </span>
                  )}
                </button>
              ))}
              {!loading && packs.length === 0 && (
                <div className="px-3 py-8 text-center text-xs text-slate-400">还没有提示词包</div>
              )}
            </div>
          </aside>

          {/* Editor */}
          <main className="min-w-0">
            {detailLoading ? (
              <div className="flex h-64 items-center justify-center rounded-3xl border border-slate-200 bg-white/85">
                <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
              </div>
            ) : !detail ? (
              <div className="flex h-64 items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-white/60 text-sm text-slate-500">
                从左侧选择一个提示词包
              </div>
            ) : (
              <div className="space-y-5">
                {/* Header + status */}
                <div className="rounded-3xl border border-slate-200 bg-white/85 p-5 shadow-sm backdrop-blur">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold text-slate-950">{detail.pack.name}</h2>
                      <p className="mt-1 text-xs text-slate-500">
                        domain_id: <span className="font-mono">{detail.pack.domain_id}</span>
                        {detail.pack.scope === 'system' && ' · 内置只读模板'}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                        detail.draft ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'
                      }`}>
                        {detail.draft ? '有未发布草稿' : '已与发布版本一致'}
                      </span>
                      {detail.published && (
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                          已发布 v{detail.published.version_no}
                        </span>
                      )}
                    </div>
                  </div>

                  {readOnly && (
                    <div className="mt-4 flex items-start gap-2.5 rounded-2xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-xs leading-5 text-slate-600">
                      <Info className="mt-0.5 h-4 w-4 shrink-0" />
                      这是内置只读模板。要修改，请点击「新建 Prompt 包」，以 <span className="font-mono">{detail.pack.domain_id}</span> 为模板创建你自己的副本。
                    </div>
                  )}

                  {detail.draft && !readOnly && (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <button
                        onClick={saveDraft}
                        disabled={saving}
                        className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                      >
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存草稿
                      </button>
                      <button
                        onClick={publish}
                        disabled={publishing}
                        className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50"
                      >
                        {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} 发布新版本
                      </button>
                      <input
                        className={`${inputClass} max-w-xs`}
                        value={changelog}
                        onChange={e => setChangelog(e.target.value)}
                        placeholder="变更说明（可选）"
                      />
                    </div>
                  )}
                </div>

                {/* Impact notice */}
                {impact && (
                  <div className={`flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm ${
                    impact.requires_rebuild
                      ? 'border-amber-200 bg-amber-50 text-amber-900'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  }`}>
                    {impact.requires_rebuild ? (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    ) : (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                    )}
                    <div>
                      <div className="font-medium">
                        {impact.requires_rebuild ? '此改动需要重新建库' : '此改动无需重新建库'}
                      </div>
                      <div className="mt-1 text-xs leading-5">{impact.message}</div>
                    </div>
                  </div>
                )}

                {/* Entity / relation types */}
                <section className="rounded-3xl border border-slate-200 bg-white/85 p-5 shadow-sm backdrop-blur">
                  <div className="mb-1 flex items-center gap-2">
                    <Layers className="h-4 w-4 text-blue-600" />
                    <h3 className="text-sm font-semibold text-slate-900">实体与关系类型</h3>
                    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">修改需重新建库</span>
                  </div>
                  <p className="mb-4 text-xs text-slate-500">
                    这些类型直接决定抽取出的图结构，因此修改后必须对知识库重新建库。
                  </p>

                  <div className="space-y-4">
                    <div>
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-600">实体类型 ({entityRows.length})</span>
                        {!readOnly && (
                          <button
                            onClick={() => setEntityRows(rows => [...rows, { name: '', description: '', examples: '' }])}
                            className="text-xs font-medium text-blue-700 hover:text-blue-800"
                          >
                            + 添加
                          </button>
                        )}
                      </div>
                      <div className="space-y-2">
                        {entityRows.map((row, index) => (
                          <div key={index} className="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)_auto]">
                            <input
                              className={inputClass}
                              value={row.name}
                              disabled={readOnly}
                              onChange={e => setEntityRows(rows => rows.map((r, i) => (i === index ? { ...r, name: e.target.value } : r)))}
                              placeholder="ACTIVE_SPECIES"
                            />
                            <input
                              className={inputClass}
                              value={row.description}
                              disabled={readOnly}
                              onChange={e => setEntityRows(rows => rows.map((r, i) => (i === index ? { ...r, description: e.target.value } : r)))}
                              placeholder="类型说明"
                            />
                            <input
                              className={inputClass}
                              value={row.examples}
                              disabled={readOnly}
                              onChange={e => setEntityRows(rows => rows.map((r, i) => (i === index ? { ...r, examples: e.target.value } : r)))}
                              placeholder="示例，逗号分隔"
                            />
                            {!readOnly && (
                              <button
                                onClick={() => setEntityRows(rows => rows.filter((_, i) => i !== index))}
                                className="rounded-lg p-2 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-600">关系类型 ({relationRows.length})</span>
                        {!readOnly && (
                          <button
                            onClick={() => setRelationRows(rows => [...rows, { name: '', description: '', examples: '' }])}
                            className="text-xs font-medium text-blue-700 hover:text-blue-800"
                          >
                            + 添加
                          </button>
                        )}
                      </div>
                      <div className="space-y-2">
                        {relationRows.map((row, index) => (
                          <div key={index} className="grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)_minmax(0,1fr)_auto]">
                            <input
                              className={inputClass}
                              value={row.name}
                              disabled={readOnly}
                              onChange={e => setRelationRows(rows => rows.map((r, i) => (i === index ? { ...r, name: e.target.value } : r)))}
                              placeholder="COMPOSITION"
                            />
                            <input
                              className={inputClass}
                              value={row.description}
                              disabled={readOnly}
                              onChange={e => setRelationRows(rows => rows.map((r, i) => (i === index ? { ...r, description: e.target.value } : r)))}
                              placeholder="关系说明"
                            />
                            <input
                              className={inputClass}
                              value={row.examples}
                              disabled={readOnly}
                              onChange={e => setRelationRows(rows => rows.map((r, i) => (i === index ? { ...r, examples: e.target.value } : r)))}
                              placeholder="示例，逗号分隔"
                            />
                            {!readOnly && (
                              <button
                                onClick={() => setRelationRows(rows => rows.filter((_, i) => i !== index))}
                                className="rounded-lg p-2 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </section>

                {/* Prompt templates */}
                <section className="rounded-3xl border border-slate-200 bg-white/85 p-5 shadow-sm backdrop-blur">
                  <div className="mb-4 flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-violet-600" />
                    <h3 className="text-sm font-semibold text-slate-900">提示词模板</h3>
                  </div>

                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {PROMPT_SECTIONS.map(section => (
                      <button
                        key={section.key}
                        onClick={() => setActiveSection(section.key)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                          activeSection === section.key
                            ? 'bg-slate-950 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                      >
                        {section.label}
                        {section.rebuild && <span className="ml-1 text-amber-500">•</span>}
                      </button>
                    ))}
                  </div>

                  <div className={`mb-3 flex items-start gap-2.5 rounded-2xl border px-3.5 py-2.5 text-xs leading-5 ${
                    activeSectionMeta.rebuild
                      ? 'border-amber-200 bg-amber-50 text-amber-800'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  }`}>
                    {activeSectionMeta.rebuild ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
                    <span>
                      {activeSectionMeta.hint} ·{' '}
                      {activeSectionMeta.rebuild ? '修改后需要重新建库' : '修改后无需重新建库'}
                    </span>
                  </div>

                  <textarea
                    className={`${inputClass} min-h-[320px] resize-y font-mono text-xs leading-6`}
                    value={prompts[activeSection] || ''}
                    disabled={readOnly}
                    onChange={e => setPrompts(prev => ({ ...prev, [activeSection]: e.target.value }))}
                    placeholder={`在此编辑 ${activeSectionMeta.label} 提示词模板...`}
                  />
                  <p className="mt-2 text-[11px] text-slate-400">
                    模板占位符（如 {'{input_text}'}、{'{entity_types}'}、{'{response_type}'}）会在运行时被填充，请保留它们。
                  </p>
                </section>

                {willAffectRebuild && (
                  <div className="flex items-start gap-2.5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    你正在编辑会改变抽取结构的提示词。发布后需要对已有知识库重新建库，新结果才会生效。
                  </div>
                )}
              </div>
            )}
          </main>

          {/* Version history */}
          <aside className="rounded-3xl border border-slate-200 bg-white/85 p-4 shadow-sm backdrop-blur">
            <div className="mb-3 flex items-center gap-2">
              <History className="h-4 w-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-slate-900">版本历史</h3>
            </div>
            {!detail ? (
              <div className="py-8 text-center text-xs text-slate-400">选择提示词包后显示</div>
            ) : (
              <div className="space-y-2">
                {detail.versions.map(version => (
                  <div
                    key={version.id}
                    className={`rounded-xl border p-3 ${
                      version.status === 'published' ? 'border-emerald-100 bg-emerald-50/50' : 'border-amber-200 bg-amber-50/50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-900">
                        v{version.version_no}
                        <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          version.status === 'published' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'
                        }`}>
                          {version.status === 'published' ? '已发布' : '草稿'}
                        </span>
                      </span>
                      {!readOnly && version.status === 'published' && (
                        <button
                          onClick={() => rollback(version.id)}
                          className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] font-medium text-blue-700 transition hover:bg-blue-50"
                          title="以该版本为内容创建新的草稿"
                        >
                          <RotateCcw className="h-3 w-3" /> 回滚
                        </button>
                      )}
                    </div>
                    {version.changelog && (
                      <p className="mt-1.5 text-[11px] leading-5 text-slate-500">{version.changelog}</p>
                    )}
                    <div className="mt-1.5 text-[10px] text-slate-400">
                      {version.published_at || version.created_at
                        ? new Date(version.published_at || version.created_at || '').toLocaleString()
                        : ''}
                    </div>
                    {version.content_hash && (
                      <div className="mt-1 truncate font-mono text-[10px] text-slate-300">{version.content_hash.slice(0, 16)}</div>
                    )}
                  </div>
                ))}
                {detail.versions.length === 0 && (
                  <div className="py-6 text-center text-xs text-slate-400">暂无版本</div>
                )}
              </div>
            )}

            {detail && (
              <div className="mt-4 border-t border-slate-100 pt-4">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-600">
                  <Database className="h-3.5 w-3.5" /> 建库绑定
                </div>
                <p className="mt-1.5 text-[11px] leading-5 text-slate-500">
                  建库与问答会记录 <span className="font-mono">pack + version</span>，可用该版本号回溯当时使用的提示词。
                </p>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}

export default observer(PromptStudio)
