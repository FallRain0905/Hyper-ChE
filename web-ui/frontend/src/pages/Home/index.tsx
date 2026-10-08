import { useEffect, useRef, useState } from 'react'
import { observer } from 'mobx-react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import { Plus, Send, Square, Trash2, GitCompare } from 'lucide-react'
import { authStore } from '@/store/auth'
import { storeGlobalUser } from '@/store/globalUser'
import { SERVER_URL } from '@/utils'
import DatabaseSelector from '@/components/DatabaseSelector'
import RetrievalEvidence from '@/components/RetrievalEvidence'
import { buildQueryPayload, queryJson, queryStream, type QueryResult } from '@/services/retrieval'

type ChatMessage = QueryResult & { id: string; role: string; content: string; timestamp: string; status?: string; error?: string; compareResults?: Array<QueryResult & { mode: string }> }
type Conversation = { id: string; title: string; messages: ChatMessage[]; createdAt: string }
const id = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
const newConversation = (): Conversation => ({ id: id(), title: '新会话', messages: [], createdAt: new Date().toISOString() })
const allModes = [{ value: 'hyper', label: 'HyperChE' }, { value: 'graph', label: '成对图 RAG' }, { value: 'naive', label: '文本 RAG' }, { value: 'hyper-lite', label: 'Hyper-RAG-Lite' }, { value: 'llm', label: '直接问答' }]

function Home() {
  const scope = authStore.user?.id || authStore.user?.email || 'anonymous'
  const storageKey = `hyperrag_conversations_v3_${scope}`
  const activeKey = `hyperrag_active_conversation_v3_${scope}`
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState('')
  const [initializedScope, setInitializedScope] = useState('')
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('hyper')
  const [compare, setCompare] = useState(false)
  const [secondMode, setSecondMode] = useState('graph')
  const [enabledModes, setEnabledModes] = useState(['hyper', 'graph', 'naive'])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<any>(null)
  const [databaseStatus, setDatabaseStatus] = useState<any>(null)
  const selectedDatabase = storeGlobalUser.selectedDatabase
  const controller = useRef<AbortController | null>(null)
  const active = conversations.find(item => item.id === activeId)
  const allowedModes = databaseStatus?.supports_modes || enabledModes
  const effectiveModes = enabledModes.filter(value => allowedModes.includes(value)).length ? enabledModes.filter(value => allowedModes.includes(value)) : allowedModes

  useEffect(() => {
    let items: Conversation[] = []
    try { items = JSON.parse(localStorage.getItem(storageKey) || '[]') } catch { items = [] }
    if (!Array.isArray(items) || !items.length) items = [newConversation()]
    // Keep the existing v3 user-scoped storage keys and migrate only message shape.
    items = items.map(item => ({ ...item, messages: (item.messages || []).map(message => ({ ...message, id: String(message.id), compareResults: message.compareResults && !Array.isArray(message.compareResults) ? Object.values(message.compareResults) : message.compareResults, status: ['generating', 'retrieving', 'evidence_ready', 'generating_answer'].includes(message.status || '') ? 'interrupted' : message.status })) }))
    setConversations(items)
    const savedActive = localStorage.getItem(activeKey)
    setActiveId(items.find(item => item.id === savedActive)?.id || items[0].id)
    setInitializedScope(scope)
    const loadModes = () => {
      try {
        const configured = JSON.parse(localStorage.getItem('hyperrag_mode_settings') || '{}').availableModes
        if (Array.isArray(configured) && configured.length) setEnabledModes(configured)
      } catch { /* Keep compatible default modes. */ }
    }
    loadModes()
    window.addEventListener('storage', loadModes)
    storeGlobalUser.restoreSelectedDatabase()
    storeGlobalUser.loadDatabases()
    let alive = true
    fetch(`${SERVER_URL}/systems/status`).then(response => response.json()).then(data => { if (alive) setStatus(data) }).catch(() => { if (alive) setStatus(null) })
    return () => { alive = false; window.removeEventListener('storage', loadModes); controller.current?.abort() }
  }, [scope, storageKey, activeKey])

  useEffect(() => {
    if (initializedScope !== scope || !conversations.length) return
    try { localStorage.setItem(storageKey, JSON.stringify(conversations)); localStorage.setItem(activeKey, activeId) } catch { /* Browser storage may be unavailable or full. */ }
  }, [conversations, activeId, initializedScope, scope, storageKey, activeKey])

  useEffect(() => {
    if (!effectiveModes.includes(mode)) setMode(effectiveModes[0] || 'hyper')
    if (!effectiveModes.includes(secondMode)) setSecondMode(effectiveModes[1] || effectiveModes[0] || 'graph')
    if (effectiveModes.length < 2) setCompare(false)
  }, [effectiveModes.join('|'), mode, secondMode])

  useEffect(() => {
    let alive = true
    setDatabaseStatus(null)
    if (selectedDatabase) fetch(`${SERVER_URL}/database/status?database=${encodeURIComponent(selectedDatabase)}`).then(response => response.json()).then(data => { if (alive) setDatabaseStatus(data) }).catch(() => undefined)
    return () => { alive = false }
  }, [selectedDatabase])

  const patchMessage = (conversationId: string, messageId: string, patch: Partial<ChatMessage>) => setConversations(current => current.map(item => item.id === conversationId ? { ...item, messages: item.messages.map(message => message.id === messageId ? { ...message, ...patch } : message) } : item))
  const create = () => { const item = newConversation(); setConversations(current => [item, ...current]); setActiveId(item.id) }
  const remove = (conversationId: string) => {
    const remaining = conversations.filter(item => item.id !== conversationId)
    const next = remaining.length ? remaining : [newConversation()]
    setConversations(next)
    if (activeId === conversationId) setActiveId(next[0].id)
  }
  const modelsReady = databaseStatus?.models_ready ?? status?.models_ready ?? status?.hyperrag?.models_ready
  const missingChannels = modelsReady === false
  const submit = async () => {
    const text = question.trim()
    if (!text || busy || !active || missingChannels) return
    const conversationId = active.id
    const messageId = id()
    const now = new Date().toISOString()
    const assistant: ChatMessage = { id: messageId, role: compare ? 'compare' : mode, content: '', timestamp: now, status: 'retrieving' }
    setConversations(current => current.map(item => item.id === conversationId ? { ...item, title: item.messages.length ? item.title : text.slice(0, 24), messages: [...item.messages, { id: id(), role: 'user', content: text, timestamp: now }, assistant] } : item))
    setQuestion('')
    setBusy(true)
    const abort = new AbortController()
    controller.current = abort
    try {
      const database = storeGlobalUser.selectedDatabase
      if (compare) {
        const modes = [mode, secondMode]
        const results = await Promise.allSettled(modes.map(value => queryJson(buildQueryPayload(text, value, database), false, abort.signal)))
        patchMessage(conversationId, messageId, { status: 'complete', content: '对比结果', compareResults: results.map((result, index) => result.status === 'fulfilled' ? { ...result.value, mode: modes[index] } : { mode: modes[index], success: false, message: String(result.reason?.message || '查询失败') }) })
      } else if (mode === 'hyper') {
        const result = await queryStream(buildQueryPayload(text, mode, database), {
          onRetrieval: evidence => patchMessage(conversationId, messageId, { ...evidence, status: 'evidence_ready' }),
          onToken: content => patchMessage(conversationId, messageId, { content, status: 'generating_answer' }),
        }, false, abort.signal)
        patchMessage(conversationId, messageId, { ...result, content: result.response || '本轮没有生成回答。', status: 'complete' })
      } else {
        const result = await queryJson(buildQueryPayload(text, mode, database), false, abort.signal)
        patchMessage(conversationId, messageId, { ...result, content: result.response || '本轮没有生成回答。', status: 'complete' })
      }
    } catch (error: any) {
      patchMessage(conversationId, messageId, { status: abort.signal.aborted ? 'cancelled' : 'error', error: abort.signal.aborted ? '已停止生成，本轮已收到的内容与证据保留。' : error?.message || '查询失败，请检查渠道配置后重试。' })
    } finally { setBusy(false); if (controller.current === abort) controller.current = null }
  }
  const label = (value: string) => allModes.find(item => item.value === value)?.label || value
  return <div className="research-workspace">
    <aside className="research-panel research-conversations"><button className="research-secondary" onClick={create}><Plus size={15} />新会话</button><div className="research-conversation-list">{conversations.map(item => <div key={item.id} className={`research-conversation-row ${item.id === activeId ? 'active' : ''}`}><button onClick={() => setActiveId(item.id)} title={item.title}>{item.title}</button><button aria-label={`删除会话 ${item.title}`} onClick={() => remove(item.id)} style={{ padding: 7 }}><Trash2 size={13} /></button></div>)}</div><div className="research-muted" style={{ fontSize: 11 }}>会话保存在当前浏览器，按登录用户区分。</div><button className="research-secondary" disabled={busy} onClick={() => { const item = newConversation(); setConversations([item]); setActiveId(item.id) }}>清空会话</button></aside>
    <section className="research-panel research-chat">
      <div className="research-chat-toolbar"><span>知识库</span><DatabaseSelector mode="select" showRefresh size="small" style={{ minWidth: 140 }} /><label>模式 <select value={mode} onChange={event => setMode(event.target.value)} disabled={busy}>{allModes.filter(item => effectiveModes.includes(item.value)).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label style={{ display: 'flex', gap: 5, alignItems: 'center' }}><input type="checkbox" checked={compare} onChange={event => setCompare(event.target.checked)} disabled={busy || effectiveModes.length < 2} /><GitCompare size={14} />对比</label>{compare && <select aria-label="第二个对比模式" value={secondMode} onChange={event => setSecondMode(event.target.value)} disabled={busy}>{allModes.filter(item => effectiveModes.includes(item.value)).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>}<span className="research-muted">最终索引自动使用混合召回与结构重排 · 5 个证据片段</span></div>
      {missingChannels && <div className="research-status research-status-warning" style={{ margin: 14 }}>模型渠道尚未配置；可以浏览已有知识库及图谱。{authStore.isAdmin ? <Link to="/app/admin"> 前往管理员后台配置公共渠道</Link> : <span> 请联系管理员，或在 <Link to="/app/providers">API 渠道</Link> 添加个人配置。</span>}</div>}
      <div className="research-chat-messages" aria-live="polite" aria-busy={busy}>
        {!active?.messages.length && <div style={{ padding: '44px 10px', maxWidth: 580, margin: 'auto' }}><div className="research-eyebrow">Research workspace</div><h1 style={{ fontSize: 28, margin: '12px 0' }}>用问题查找实验条件与原始证据</h1><p className="research-muted">选择知识库，输入化工或材料问题。回答、来源片段和检索超图来自同一次查询；旧知识库自动保持兼容。</p><a className="research-secondary" href="/report/hyperche-demo.html#platform" target="_blank" rel="noreferrer">查看已归档的真实超图案例</a></div>}
        {active?.messages.map(message => <article className={`research-message ${message.role === 'user' ? 'user' : ''}`} key={message.id}><div className="research-message-head"><strong>{message.role === 'user' ? '你' : message.role === 'compare' ? '模式对比' : label(message.role)}</strong><span>{message.status === 'retrieving' ? '正在检索' : message.status === 'evidence_ready' ? '证据已就绪，等待生成' : message.status === 'generating_answer' ? '正在生成回答' : message.status === 'interrupted' ? '上次请求已中断' : new Date(message.timestamp).toLocaleTimeString()}</span></div><div className="research-message-body">{message.compareResults ? <div className="research-comparison">{message.compareResults.map((result, index) => <div key={`${result.mode}-${index}`}><h3>{label(result.mode)}</h3><ReactMarkdown>{result.response || result.message || ''}</ReactMarkdown><RetrievalEvidence result={result} mode={result.mode} graphId={`compare-${message.id}-${index}`} /></div>)}</div> : <><ReactMarkdown>{message.content || (message.status === 'retrieving' ? '正在检索与组织证据…' : message.status === 'evidence_ready' ? '本轮证据已就绪，正在等待回答…' : '')}</ReactMarkdown>{message.role !== 'user' && <RetrievalEvidence result={message} mode={message.role} graphId={`retrieval-${message.id}`} />}</>}{message.error && <div className="research-status research-status-warning" style={{ marginTop: 12 }}>{message.error}</div>}</div></article>)}
      </div>
      <form className="research-composer" onSubmit={event => { event.preventDefault(); submit() }}><textarea aria-label="输入问题" value={question} onChange={event => setQuestion(event.target.value)} placeholder="例如：比较不同电解液条件下的库仑效率，并定位实验条件与来源。" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit() } }} /><div className="research-composer-actions"><span>Enter 发送 · Shift + Enter 换行</span>{busy ? <button type="button" className="research-secondary" onClick={() => controller.current?.abort()}><Square size={14} />停止</button> : <button className="research-primary" disabled={!question.trim() || missingChannels}><Send size={14} />发送</button>}</div></form>
    </section>
  </div>
}
export default observer(Home)
