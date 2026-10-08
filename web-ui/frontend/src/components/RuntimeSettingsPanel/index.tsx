import { useEffect, useState } from 'react'
import { message } from 'antd'
import { Activity, Save, SlidersHorizontal } from 'lucide-react'
import { SERVER_URL } from '@/utils'

type RuntimeSettings = {
  hyperrag_domain: string
  experimentMode: string
  promptProfile: string
  indexProfile: string
  enableEntityNormalization: boolean
  enableMeasurementInstances: boolean
  enableEfuRepair: boolean
  enableHybridRerank: boolean
}

const defaults: RuntimeSettings = {
  hyperrag_domain: 'default',
  experimentMode: 'hyper_final',
  promptProfile: 'chemistry',
  indexProfile: 'dual_concat',
  enableEntityNormalization: true,
  enableMeasurementInstances: true,
  enableEfuRepair: true,
  enableHybridRerank: true,
}

const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10'

export default function RuntimeSettingsPanel() {
  const [settings, setSettings] = useState<RuntimeSettings>(defaults)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch(`${SERVER_URL}/user-runtime-settings`, { credentials: 'include' })
      .then(async response => {
        const data = await response.json()
        if (!response.ok || data?.success === false) throw new Error(data?.detail || data?.message || '加载失败')
        setSettings({ ...defaults, ...(data.settings || {}) })
      })
      .catch(error => message.error(error?.message || '无法加载 HyperRAG 运行配置'))
      .finally(() => setLoading(false))
  }, [])

  const update = <K extends keyof RuntimeSettings>(key: K, value: RuntimeSettings[K]) => {
    setSettings(current => ({ ...current, [key]: value }))
  }

  const save = async () => {
    setSaving(true)
    try {
      const response = await fetch(`${SERVER_URL}/user-runtime-settings`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || data?.success === false) throw new Error(data?.detail || data?.message || '保存失败')
      setSettings({ ...defaults, ...(data.settings || {}) })
      message.success('个人 HyperRAG 运行配置已保存')
    } catch (error: any) {
      message.error(error?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggles: Array<{ key: keyof RuntimeSettings; title: string; desc: string }> = [
    { key: 'enableEntityNormalization', title: '实体归一化', desc: '合并同义实体与规范化名称' },
    { key: 'enableMeasurementInstances', title: '测量实例', desc: '保留实验数值及测量上下文' },
    { key: 'enableEfuRepair', title: 'EFU Repair', desc: '启用抽取结果修复流程' },
    { key: 'enableHybridRerank', title: '混合重排', desc: '融合语义与超图结构结果' },
  ]

  return (
    <section className="hyperche-card mb-6 overflow-hidden rounded-3xl border border-slate-200 bg-white/90 shadow-sm backdrop-blur">
      <div className="flex flex-col gap-3 border-b border-slate-100 bg-gradient-to-r from-slate-50 to-white px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-700"><SlidersHorizontal className="h-5 w-5" /></div>
          <div><h2 className="font-semibold text-slate-950">HyperRAG 运行配置</h2><p className="mt-1 text-sm leading-6 text-slate-500">这些参数只作用于你的工作台，不会影响其他用户。</p></div>
        </div>
        <button type="button" onClick={save} disabled={loading || saving} className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-slate-800 disabled:opacity-50"><Save className="h-4 w-4" />{saving ? '保存中…' : '保存个人配置'}</button>
      </div>
      <div className="p-5 sm:p-6">
        {loading ? <div className="flex items-center gap-2 text-sm text-slate-500"><Activity className="h-4 w-4 animate-pulse" />正在加载配置…</div> : <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <label className="text-sm font-medium text-slate-700">领域<input className={`${inputClass} mt-1.5`} value={settings.hyperrag_domain} onChange={e => update('hyperrag_domain', e.target.value)} placeholder="default" /></label>
            <label className="text-sm font-medium text-slate-700">实验模式<input className={`${inputClass} mt-1.5`} value={settings.experimentMode} onChange={e => update('experimentMode', e.target.value)} /></label>
            <label className="text-sm font-medium text-slate-700">Prompt Profile<input className={`${inputClass} mt-1.5`} value={settings.promptProfile} onChange={e => update('promptProfile', e.target.value)} /></label>
            <label className="text-sm font-medium text-slate-700">Index Profile<input className={`${inputClass} mt-1.5`} value={settings.indexProfile} onChange={e => update('indexProfile', e.target.value)} /></label>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {toggles.map(item => <button key={item.key} type="button" onClick={() => update(item.key, !settings[item.key] as never)} className={`rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 ${settings[item.key] ? 'border-blue-200 bg-blue-50/70 shadow-sm' : 'border-slate-200 bg-slate-50'}`}><span className="flex items-center justify-between gap-2"><span className="font-medium text-slate-900">{item.title}</span><span className={`h-5 w-9 rounded-full p-0.5 transition ${settings[item.key] ? 'bg-blue-600' : 'bg-slate-300'}`}><span className={`block h-4 w-4 rounded-full bg-white transition ${settings[item.key] ? 'translate-x-4' : ''}`} /></span></span><span className="mt-1 block text-xs leading-5 text-slate-500">{item.desc}</span></button>)}
          </div>
        </>}
      </div>
    </section>
  )
}
