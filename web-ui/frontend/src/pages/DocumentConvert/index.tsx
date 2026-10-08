import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { message } from 'antd'
import {
  CheckCircle2,
  Clipboard,
  CloudUpload,
  Download,
  FileText,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  WandSparkles,
  X,
} from 'lucide-react'
import { SERVER_URL } from '@/utils'

type MinerUConfig = {
  configured: boolean
  model_version: string
  language: string
  enable_ocr: boolean
  enable_formula: boolean
  enable_table: boolean
  poll_interval_seconds: number
  max_poll_attempts: number
  max_file_mb: number
  allowed_extensions: string[]
}

type TaskState = 'idle' | 'uploading' | 'processing' | 'done' | 'failed'

const initialConfig: MinerUConfig = {
  configured: false,
  model_version: 'pipeline',
  language: 'ch',
  enable_ocr: true,
  enable_formula: true,
  enable_table: true,
  poll_interval_seconds: 3,
  max_poll_attempts: 100,
  max_file_mb: 200,
  allowed_extensions: [],
}

async function readJson(response: Response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data?.success === false) throw new Error(data?.detail || data?.message || `请求失败（${response.status}）`)
  return data
}

export default function DocumentConvert() {
  const [config, setConfig] = useState(initialConfig)
  const [configLoading, setConfigLoading] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [taskState, setTaskState] = useState<TaskState>('idle')
  const [batchId, setBatchId] = useState('')
  const [progress, setProgress] = useState(0)
  const [statusText, setStatusText] = useState('等待上传文档')
  const [markdown, setMarkdown] = useState('')
  const [zipUrl, setZipUrl] = useState('')
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const pollTimer = useRef<number | null>(null)
  const attempts = useRef(0)

  const stopPolling = () => {
    if (pollTimer.current) window.clearTimeout(pollTimer.current)
    pollTimer.current = null
  }

  useEffect(() => {
    fetch(`${SERVER_URL}/document-convert/mineru/config`, { credentials: 'include' })
      .then(readJson)
      .then(data => setConfig({ ...initialConfig, ...data }))
      .catch(err => setError(err?.message || '无法读取 MinerU 配置'))
      .finally(() => setConfigLoading(false))
    return stopPolling
  }, [])

  const chooseFile = (next: File | null) => {
    stopPolling()
    setFile(next)
    setBatchId('')
    setMarkdown('')
    setZipUrl('')
    setError('')
    setProgress(0)
    setTaskState('idle')
    setStatusText(next ? '文档已就绪' : '等待上传文档')
  }

  const fetchResult = useCallback(async (id: string) => {
    const data = await fetch(`${SERVER_URL}/document-convert/mineru/${id}/result`, { credentials: 'include' }).then(readJson)
    setMarkdown(data.markdown || '')
    setZipUrl(data.full_zip_url || '')
    setProgress(100)
    setTaskState('done')
    setStatusText('转换完成')
  }, [])

  const pollStatus = useCallback(async (id: string) => {
    try {
      attempts.current += 1
      const data = await fetch(`${SERVER_URL}/document-convert/mineru/${id}`, { credentials: 'include' }).then(readJson)
      const state = String(data.state || 'pending').toLowerCase()
      const percent = Number(data.progress?.percent || 0)
      setProgress(percent)
      setStatusText(state === 'running' || state === 'processing' ? 'MinerU 正在解析文档' : '任务已提交，等待处理')
      if (['done', 'completed', 'success'].includes(state)) {
        await fetchResult(id)
        return
      }
      if (['failed', 'error'].includes(state)) throw new Error(data.error || 'MinerU 转换失败')
      if (attempts.current >= config.max_poll_attempts) throw new Error('转换等待超时，请稍后重试')
      pollTimer.current = window.setTimeout(() => pollStatus(id), Math.max(1, config.poll_interval_seconds) * 1000)
    } catch (err: any) {
      setTaskState('failed')
      setError(err?.message || '查询转换状态失败')
      setStatusText('转换失败')
    }
  }, [config.max_poll_attempts, config.poll_interval_seconds, fetchResult])

  const startConvert = async () => {
    if (!file) return message.warning('请先选择文档')
    if (!config.configured) return message.warning('MinerU 尚未配置，请联系管理员')
    setTaskState('uploading')
    setStatusText('正在上传到 MinerU')
    setProgress(6)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const data = await fetch(`${SERVER_URL}/document-convert/mineru`, { method: 'POST', credentials: 'include', body: form }).then(readJson)
      setBatchId(data.batch_id)
      setTaskState('processing')
      setStatusText('任务已提交，等待处理')
      setProgress(12)
      attempts.current = 0
      await pollStatus(data.batch_id)
    } catch (err: any) {
      setTaskState('failed')
      setStatusText('上传或提交失败')
      setError(err?.message || '提交失败')
    }
  }

  const downloadMarkdown = () => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${(file?.name || 'mineru-result').replace(/\.[^.]+$/, '')}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const busy = taskState === 'uploading' || taskState === 'processing'

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
      <div className="hyperche-grid pointer-events-none absolute inset-0 opacity-40" />
      <div className="hyperche-drift pointer-events-none absolute -right-24 top-12 h-72 w-72 rounded-full bg-blue-200/30 blur-3xl" />
      <div className="relative mx-auto max-w-7xl">
        <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div><div className="mb-2 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700"><WandSparkles className="h-3.5 w-3.5" /> MinerU Document Engine</div><h1 className="text-3xl font-semibold tracking-tight text-slate-950">文档转换</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">上传 PDF、Office 文档、图片或 HTML，转换为便于知识库入库与编辑的 Markdown。</p></div>
          <div className="flex flex-wrap gap-2 text-xs text-slate-500"><span className="rounded-full border border-slate-200 bg-white px-3 py-1.5">{config.model_version}</span><span className="rounded-full border border-slate-200 bg-white px-3 py-1.5">最大 {config.max_file_mb} MB</span><span className={`rounded-full border px-3 py-1.5 ${config.configured ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>{config.configured ? '服务已配置' : '等待管理员配置'}</span></div>
        </header>

        {!configLoading && !config.configured && <div className="mb-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">MinerU API Token 尚未配置。管理员可在“管理员后台 → MinerU 文档转换”中填写完整 API 设置。</div>}
        {error && <div className="mb-5 flex items-start justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><span>{error}</span><button onClick={() => setError('')}><X className="h-4 w-4" /></button></div>}

        <div className="grid gap-6 xl:grid-cols-[0.82fr_1.18fr]">
          <section className="hyperche-card rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-sm backdrop-blur sm:p-6">
            <div onDragOver={event => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files?.[0] || null) }} onClick={() => !busy && fileInput.current?.click()} className={`group flex min-h-64 cursor-pointer flex-col items-center justify-center rounded-3xl border border-dashed p-6 text-center transition ${dragging ? 'scale-[1.01] border-blue-500 bg-blue-50' : 'border-slate-300 bg-slate-50/70 hover:border-blue-300 hover:bg-blue-50/40'}`}>
              <input ref={fileInput} className="hidden" type="file" onChange={event => chooseFile(event.target.files?.[0] || null)} accept={config.allowed_extensions.join(',')} />
              <div className="hyperche-float flex h-16 w-16 items-center justify-center rounded-3xl border border-blue-100 bg-white text-blue-600 shadow-sm"><CloudUpload className="h-7 w-7" /></div>
              <h2 className="mt-5 text-lg font-semibold text-slate-950">拖拽文档到这里</h2><p className="mt-2 text-sm text-slate-500">或点击选择文件 · 单文件最大 {config.max_file_mb} MB</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">{['PDF', 'Word', 'PPT', 'Image', 'HTML'].map(type => <span key={type} className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-500">{type}</span>)}</div>
            </div>

            {file && <div className="mt-4 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><FileText className="h-5 w-5" /></div><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-slate-900">{file.name}</p><p className="mt-1 text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p></div>{!busy && <button onClick={event => { event.stopPropagation(); chooseFile(null) }} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-4 w-4" /></button>}</div>}

            <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center justify-between gap-3 text-sm"><span className="flex items-center gap-2 font-medium text-slate-800">{taskState === 'done' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : busy ? <LoaderCircle className="h-4 w-4 animate-spin text-blue-600" /> : <Sparkles className="h-4 w-4 text-slate-500" />}{statusText}</span><span className="font-mono text-xs text-slate-500">{progress}%</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-gradient-to-r from-slate-800 to-blue-600 transition-all duration-700" style={{ width: `${progress}%` }} /></div>{batchId && <p className="mt-2 truncate font-mono text-[11px] text-slate-400">Batch: {batchId}</p>}</div>

            <button onClick={startConvert} disabled={!file || !config.configured || busy || configLoading} className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-800 disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40">{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : taskState === 'failed' ? <RefreshCw className="h-4 w-4" /> : <WandSparkles className="h-4 w-4" />}{taskState === 'failed' ? '重新转换' : busy ? '转换中…' : '开始转换'}</button>
          </section>

          <section className="hyperche-card flex min-h-[660px] flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white/90 shadow-sm backdrop-blur">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6"><div><h2 className="font-semibold text-slate-950">Markdown 预览</h2><p className="mt-1 text-xs text-slate-500">转换完成后可复制、下载 Markdown 或取得 MinerU 原始 ZIP。</p></div><div className="flex gap-2"><button disabled={!markdown} onClick={() => navigator.clipboard.writeText(markdown).then(() => message.success('已复制 Markdown'))} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"><Clipboard className="h-3.5 w-3.5" />复制</button><button disabled={!markdown} onClick={downloadMarkdown} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"><Download className="h-3.5 w-3.5" />Markdown</button>{zipUrl && <a href={zipUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-xl bg-slate-950 px-3 py-2 text-xs font-medium text-white transition hover:bg-slate-800"><Download className="h-3.5 w-3.5" />结果 ZIP</a>}</div></div>
            <div className="min-h-0 flex-1 overflow-auto p-5 sm:p-7">{markdown ? <article className="prose prose-slate max-w-none"><ReactMarkdown>{markdown}</ReactMarkdown></article> : <div className="flex h-full min-h-[500px] flex-col items-center justify-center text-center"><div className="hyperche-pulse flex h-20 w-20 items-center justify-center rounded-[2rem] border border-slate-200 bg-slate-50 text-slate-400"><FileText className="h-8 w-8" /></div><h3 className="mt-5 font-medium text-slate-800">等待转换结果</h3><p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">处理期间可以留在此页面。完成后 Markdown 会自动加载到预览区。</p></div>}</div>
          </section>
        </div>
      </div>
    </main>
  )
}
