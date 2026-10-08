import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { Send, Square } from 'lucide-react'
import ResearchDock from '@/components/ResearchDock'
import RetrievalHyperGraph from '@/components/RetrievalHyperGraph'
import RetrievalEvidence from '@/components/RetrievalEvidence'
import { SERVER_URL } from '@/utils'
import { PUBLIC_DEMO, type PublicDemoStatus } from '@/config/publicDemo'
import { buildQueryPayload, queryJson, queryStream, type QueryResult } from '@/services/retrieval'

type DemoMessage = QueryResult & { id: string; role: 'user' | 'assistant'; content: string; status?: string; error?: string }
const newId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
export default function TryDemo() {
  const [status, setStatus] = useState<PublicDemoStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [statusError, setStatusError] = useState('')
  const [offline, setOffline] = useState<QueryResult | null>(null)
  const [offlineLoading, setOfflineLoading] = useState(true)
  const [offlineError, setOfflineError] = useState('')
  const [offlineRetry, setOfflineRetry] = useState(0)
  const [messages, setMessages] = useState<DemoMessage[]>([])
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('hyper')
  const [busy, setBusy] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const statusController = useRef<AbortController | null>(null)
  const ready = !statusLoading && !statusError && status?.ready === true
  const checkStatus = useCallback(async () => {
    statusController.current?.abort()
    const abort = new AbortController()
    statusController.current = abort
    setStatusLoading(true)
    setStatusError('')
    try {
      const response = await fetch(`${SERVER_URL}/public/demo/status`, { signal: abort.signal })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `服务状态检查失败（${response.status}），请稍后重新检查。`)
      if (data.success === false || typeof data.ready !== 'boolean') throw new Error('服务状态返回异常，请重新检查。')
      if (statusController.current === abort && !abort.signal.aborted) setStatus(data)
    } catch (error: any) {
      if (statusController.current === abort && !abort.signal.aborted) {
        setStatus(null)
        setStatusError(error?.message || '无法连接公开体验服务，请检查网络后重试。')
      }
    } finally {
      if (statusController.current === abort && !abort.signal.aborted) {
        setStatusLoading(false)
        statusController.current = null
      }
    }
  }, [])
  useEffect(() => {
    void checkStatus()
    return () => { statusController.current?.abort(); controller.current?.abort() }
  }, [checkStatus])
  useEffect(() => {
    const abort = new AbortController()
    setOfflineLoading(true)
    setOfflineError('')
    fetch(`${SERVER_URL}/public/demo/graph?edge_limit=12`, { signal: abort.signal })
      .then(async response => {
        const data = await response.json()
        if (!response.ok || data.success === false) throw new Error('缓存超图暂时无法加载，请重新加载。')
        if (!abort.signal.aborted) setOffline(data)
      })
      .catch(() => { if (!abort.signal.aborted) setOfflineError('缓存超图暂时无法加载，请重新加载。') })
      .finally(() => { if (!abort.signal.aborted) setOfflineLoading(false) })
    return () => abort.abort()
  }, [offlineRetry])
  const patch = (id: string, updates: Partial<DemoMessage>) => setMessages(current => current.map(message => message.id === id ? { ...message, ...updates } : message))
  const ask = async (input: string) => {
    const text = input.trim()
    if (!text || busy || !ready) return
    const assistantId = newId()
    const abort = new AbortController()
    controller.current = abort
    setMessages(current => [...current, { id: newId(), role: 'user', content: text }, { id: assistantId, role: 'assistant', content: '', status: 'retrieving' }])
    setQuestion('')
    setBusy(true)
    try {
      const payload = buildQueryPayload(text, mode)
      const result = mode === 'hyper' ? await queryStream(payload, { onRetrieval: evidence => patch(assistantId, { ...evidence, status: 'evidence_ready' }), onToken: content => patch(assistantId, { content, status: 'generating_answer' }) }, true, abort.signal) : await queryJson(payload, true, abort.signal)
      patch(assistantId, { ...result, content: result.response || '没有生成回答。', status: 'complete' })
    } catch (error: any) {
      patch(assistantId, { error: abort.signal.aborted ? '已停止，已收到的回答和证据保留。' : error?.message || '查询失败，请稍后重试。', status: abort.signal.aborted ? 'cancelled' : 'error' })
    } finally { setBusy(false); if (controller.current === abort) controller.current = null }
  }
  return <div className="research-page" style={{ minHeight: '100dvh' }}><ResearchDock publicPage actions={<Link to="/app/Hyper/chat" className="research-primary">登录工作台</Link>} /><main style={{ maxWidth: 1240, margin: 'auto', padding: '28px 20px' }}>
    <div className="research-eyebrow">Public knowledge base</div><h1 style={{ fontSize: 28, margin: '10px 0' }}>液流电池公开体验</h1><p className="research-muted">固定只读知识库。检索、来源证据与回答来自同一次查询；免费体验受公共额度限制。</p>
    <div className={`research-status ${ready ? '' : 'research-status-warning'}`} style={{ margin: '18px 0' }} role="status" aria-live="polite">{statusLoading ? '正在检查公开知识库和模型渠道…' : statusError ? `状态检查失败：${statusError}` : ready ? '知识库与模型渠道已就绪，可提交问题。' : status?.cache_ready === false || status?.cache_exists === false ? '公开知识库暂未就绪，请先查看项目汇报。' : '知识库缓存可浏览；模型渠道尚未配置，在线检索问答暂未开放。'} <button type="button" className="research-secondary" onClick={() => { void checkStatus() }} disabled={statusLoading || busy} style={{ marginLeft: 8 }}>{statusLoading ? '检查中…' : '重新检查'}</button>{!ready && !statusLoading && <span> <a href="/report/hyperche-demo.html#platform" target="_blank" rel="noreferrer">查看已归档的真实超图案例</a> · <Link to="/app/Hyper/chat">管理员登录配置渠道</Link></span>}</div>
    <div className="research-public-grid"><section className="research-panel research-chat"><div className="research-chat-toolbar"><strong>检索问答</strong><label>模式 <select value={mode} onChange={event => setMode(event.target.value)} disabled={busy}><option value="hyper">HyperChE</option>{status?.supports_modes?.includes('graph') && <option value="graph">成对图 RAG</option>}</select></label><span className="research-muted">最终索引返回 top-5 证据</span></div>
      <div className="research-chat-messages" aria-live="polite" aria-busy={busy}>{!messages.length && <div><h2 style={{ fontSize: 18, marginBottom: 15 }}>示例问题</h2>{PUBLIC_DEMO.suggestedQuestions.slice(0, 4).map(item => <button key={item} disabled={busy} className="research-secondary" style={{ display: 'block', width: '100%', textAlign: 'left', margin: '8px 0', fontSize: 12 }} onClick={() => ready ? ask(item) : setQuestion(item)}>{item}</button>)}</div>}{messages.map(message => <article key={message.id} className={`research-message ${message.role === 'user' ? 'user' : ''}`}><div className="research-message-head"><strong>{message.role === 'user' ? '你' : 'HyperChE'}</strong><span>{message.status === 'retrieving' ? '正在检索' : message.status === 'evidence_ready' ? '证据已就绪' : message.status === 'generating_answer' ? '正在生成回答' : ''}</span></div><div className="research-message-body"><ReactMarkdown>{message.content || (message.status === 'retrieving' ? '正在检索与组织证据…' : message.status === 'evidence_ready' ? '证据已就绪，等待生成回答…' : '')}</ReactMarkdown>{message.role === 'assistant' && <RetrievalEvidence result={message} mode={mode} graphId={`public-query-${message.id}`} />}{message.error && <p className="research-status research-status-warning">{message.error}</p>}</div></article>)}</div>
      <form className="research-composer" onSubmit={event => { event.preventDefault(); ask(question) }}><textarea aria-label="公开体验问题" value={question} onChange={event => setQuestion(event.target.value)} placeholder="输入关于液流电池的问题" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); ask(question) } }} /><div className="research-composer-actions"><span>{ready ? 'Enter 发送 · Shift + Enter 换行' : '模型渠道配置完成后可发送'}</span>{busy ? <button type="button" className="research-secondary" onClick={() => controller.current?.abort()}><Square size={14} />停止</button> : <button className="research-primary" disabled={!ready || !question.trim()}><Send size={14} />发送</button>}</div></form></section>
      <aside><div className="research-panel" style={{ padding: 18, marginBottom: 12 }}><h2 style={{ fontSize: 17 }}>真实缓存超图</h2><p className="research-muted" style={{ fontSize: 12, margin: '8px 0 14px' }}>离线局部案例，可在无模型渠道时浏览。它不是当前问题的在线检索结果。</p>{offline && ((offline.entities?.length || 0) > 0 || (offline.hyperedges?.length || 0) > 0) ? <RetrievalHyperGraph entities={offline.entities || []} hyperedges={offline.hyperedges || []} graphId="public-offline-cache-graph" height="420px" /> : <div role="status"><p className="research-muted">{offlineLoading ? '正在加载只读缓存超图，首次加载需要稍候…' : offlineError || '暂无可展示的局部超图。'}</p>{!offlineLoading && <button type="button" className="research-secondary" onClick={() => setOfflineRetry(current => current + 1)}>重新加载超图</button>} <a className="research-secondary" href="/report/hyperche-demo.html#platform" target="_blank" rel="noreferrer">打开已归档案例</a></div>}</div></aside>
    </div>
  </main></div>
}
