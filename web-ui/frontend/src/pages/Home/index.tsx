import { useEffect, useRef, useState } from 'react'
import { observer } from 'mobx-react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import { Plus, Send, Square, Trash2, GitCompare, Menu, X } from 'lucide-react'
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
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [mobileView, setMobileView] = useState<'answer' | 'evidence'>('answer')
  const [evidenceMessageId, setEvidenceMessageId] = useState('')
  const selectedDatabase = storeGlobalUser.selectedDatabase
  const controller = useRef<AbortController | null>(null)
  const drawer = useRef<HTMLElement | null>(null)
  const active = conversations.find(item => item.id === activeId)
  const assistantMessages = (active?.messages || []).filter(message => message.role !== 'user')
  const latestAssistantId = assistantMessages[assistantMessages.length - 1]?.id || ''
  const evidenceMessage = assistantMessages.find(message => message.id === evidenceMessageId) || assistantMessages[assistantMessages.length - 1]
  const allowedModes = databaseStatus?.supports_modes || enabledModes
  const effectiveModes = enabledModes.filter(value => allowedModes.includes(value)).length ? enabledModes.filter(value => allowedModes.includes(value)) : allowedModes

  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const update = () => { setIsMobile(media.matches); if (!media.matches) setDrawerOpen(false) }
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    setDrawerOpen(false)
    setMobileView('answer')
  }, [activeId])

  useEffect(() => { setEvidenceMessageId(latestAssistantId) }, [activeId, latestAssistantId])

  useEffect(() => {
    if (!isMobile || !drawerOpen) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    drawer.current?.querySelector<HTMLButtonElement>('button')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setDrawerOpen(false); return }
      if (event.key !== 'Tab') return
      const controls = Array.from(drawer.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]') || [])
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (!first || !last) return
      if (!drawer.current?.contains(document.activeElement)) { event.preventDefault(); first.focus() }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
      if (previousFocus && document.contains(previousFocus)) previousFocus.focus()
    }
  }, [isMobile, drawerOpen])

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
  const modelStatus = databaseStatus || status || {}
  const configurationReason = modelStatus.configuration_reason || status?.hyperrag?.configuration_reason
  const configurationMessage = configurationReason === 'embedding_model_mismatch'
    ? `当前 embedding 为 ${modelStatus.configured_embedding_model || '未识别模型'}，最终知识库要求 Qwen/Qwen3-Embedding-4B（${modelStatus.required_embedding_dim || 2560} 维）。`
    : configurationReason === 'embedding_dimension_mismatch'
      ? `当前 embedding 维度为 ${modelStatus.configured_embedding_dim || '未识别'}，最终知识库要求 ${modelStatus.required_embedding_dim || 2560} 维。`
      : configurationReason === 'missing_embedding_channel'
        ? '尚未配置可用的 embedding 渠道。'
        : '尚未配置可用的回答渠道。'
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
  const hasEvidence = (result: QueryResult) => Boolean(result.entities?.length || result.hyperedges?.length || result.text_units?.length || Object.keys(result.retrieval_meta || {}).length)
  const openEvidence = (messageId: string) => { setEvidenceMessageId(messageId); setMobileView('evidence') }
  const renderMobileEvidence = (message: ChatMessage) => message.compareResults ? <div className="research-comparison">{message.compareResults.map((result, index) => <section key={`${message.id}-${result.mode}-${index}`}><h3>{label(result.mode)}</h3>{hasEvidence(result) ? <RetrievalEvidence result={result} mode={result.mode} graphId={`mobile-compare-${message.id}-${index}`} /> : <p className="research-muted">{result.message || '此模式未返回检索证据。'}</p>}</section>)}</div> : hasEvidence(message) ? <RetrievalEvidence key={message.id} result={message} mode={message.role} graphId={`mobile-retrieval-${message.id}`} /> : <p className="research-muted">{message.status === 'retrieving' ? '正在检索，本轮证据将在收到后显示。' : message.role === 'llm' ? '直接问答模式没有检索证据。' : '本轮尚未收到检索证据；已有回答和错误信息保留在回答标签中。'}</p>
  return <div className="research-workspace">
    <div className="research-mobile-conversation-bar"><button type="button" className="research-secondary" aria-label="打开会话列表" aria-expanded={drawerOpen} aria-controls="research-conversation-drawer" onClick={() => setDrawerOpen(true)}><Menu size={16} />会话</button><strong title={active?.title}>{active?.title || '新会话'}</strong></div>
    {isMobile && drawerOpen && <button type="button" className="research-conversation-backdrop" aria-label="关闭会话列表" onClick={() => setDrawerOpen(false)} />}
    <aside ref={drawer} id="research-conversation-drawer" className="research-panel research-conversations" hidden={isMobile && !drawerOpen} role={isMobile ? 'dialog' : undefined} aria-modal={isMobile && drawerOpen ? true : undefined} aria-label="会话列表">
      <div className="research-mobile-drawer-head"><strong>会话</strong><button type="button" className="research-secondary" aria-label="关闭会话列表" onClick={() => setDrawerOpen(false)}><X size={17} /></button></div>
      <button className="research-secondary" onClick={create}><Plus size={15} />新会话</button><div className="research-conversation-list">{conversations.map(item => <div key={item.id} className={`research-conversation-row ${item.id === activeId ? 'active' : ''}`}><button onClick={() => { setActiveId(item.id); setDrawerOpen(false) }} title={item.title}>{item.title}</button><button aria-label={`删除会话 ${item.title}`} onClick={() => remove(item.id)} style={{ padding: 7 }}><Trash2 size={13} /></button></div>)}</div><div className="research-muted" style={{ fontSize: 11 }}>会话保存在当前浏览器，按登录用户区分。</div><button className="research-secondary" disabled={busy} onClick={() => { const item = newConversation(); setConversations([item]); setActiveId(item.id) }}>清空会话</button>
    </aside>
    <section className="research-panel research-chat">
      <div className="research-chat-toolbar"><span>知识库</span><DatabaseSelector mode="select" showRefresh size="small" style={{ minWidth: 140 }} /><label>模式 <select value={mode} onChange={event => setMode(event.target.value)} disabled={busy}>{allModes.filter(item => effectiveModes.includes(item.value)).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label style={{ display: 'flex', gap: 5, alignItems: 'center' }}><input type="checkbox" checked={compare} onChange={event => setCompare(event.target.checked)} disabled={busy || effectiveModes.length < 2} /><GitCompare size={14} />对比</label>{compare && <select aria-label="第二个对比模式" value={secondMode} onChange={event => setSecondMode(event.target.value)} disabled={busy}>{allModes.filter(item => effectiveModes.includes(item.value)).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select>}<span className="research-muted">最终索引自动使用混合召回与结构重排 · 5 个证据片段</span></div>
       {missingChannels && <div className="research-status research-status-warning" style={{ margin: 14 }}>{configurationMessage} 可以浏览已有知识库及图谱。{authStore.isAdmin ? <Link to="/app/admin"> 前往管理员后台配置公共渠道</Link> : <span> 请联系管理员，或在 <Link to="/app/providers">API 渠道</Link> 添加个人配置。</span>}</div>}
      {isMobile && <div className="research-mobile-view-tabs" role="tablist" aria-label="问答视图" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const next = event.key === 'Home' ? 'answer' : event.key === 'End' ? 'evidence' : mobileView === 'answer' ? 'evidence' : 'answer'
        setMobileView(next)
        document.getElementById(`research-workspace-${next}-tab`)?.focus()
      }}><button type="button" id="research-workspace-answer-tab" role="tab" aria-selected={mobileView === 'answer'} aria-controls="research-workspace-answer-panel" tabIndex={mobileView === 'answer' ? 0 : -1} onClick={() => setMobileView('answer')}>回答</button><button type="button" id="research-workspace-evidence-tab" role="tab" aria-selected={mobileView === 'evidence'} aria-controls="research-workspace-evidence-panel" tabIndex={mobileView === 'evidence' ? 0 : -1} onClick={() => setMobileView('evidence')}>本轮证据</button></div>}
      <div id="research-workspace-answer-panel" className="research-chat-messages" hidden={isMobile && mobileView !== 'answer'} role={isMobile ? 'tabpanel' : undefined} aria-labelledby={isMobile ? 'research-workspace-answer-tab' : undefined} aria-live="polite" aria-busy={busy}>
        {!active?.messages.length && <div style={{ padding: '44px 10px', maxWidth: 580, margin: 'auto' }}><div className="research-eyebrow">Research workspace</div><h1 style={{ fontSize: 28, margin: '12px 0' }}>用问题查找实验条件与原始证据</h1><p className="research-muted">选择知识库，输入化工或材料问题。回答、来源片段和检索超图来自同一次查询；旧知识库自动保持兼容。</p><a className="research-secondary" href="/#platform">查看已归档的真实超图案例</a></div>}
        {active?.messages.map(message => <article className={`research-message ${message.role === 'user' ? 'user' : ''}`} key={message.id}><div className="research-message-head"><strong>{message.role === 'user' ? '你' : message.role === 'compare' ? '模式对比' : label(message.role)}</strong><span>{message.status === 'retrieving' ? '正在检索' : message.status === 'evidence_ready' ? '证据已就绪，等待生成' : message.status === 'generating_answer' ? '正在生成回答' : message.status === 'interrupted' ? '上次请求已中断' : new Date(message.timestamp).toLocaleTimeString()}</span></div><div className="research-message-body">{message.compareResults ? <div className="research-comparison">{message.compareResults.map((result, index) => <div key={`${result.mode}-${index}`}><h3>{label(result.mode)}</h3><ReactMarkdown>{result.response || result.message || ''}</ReactMarkdown>{!isMobile && <RetrievalEvidence result={result} mode={result.mode} graphId={`compare-${message.id}-${index}`} />}</div>)}</div> : <><ReactMarkdown>{message.content || (message.status === 'retrieving' ? '正在检索与组织证据…' : message.status === 'evidence_ready' ? '本轮证据已就绪，正在等待回答…' : '')}</ReactMarkdown>{!isMobile && message.role !== 'user' && <RetrievalEvidence result={message} mode={message.role} graphId={`retrieval-${message.id}`} />}</>}{isMobile && message.role !== 'user' && <button type="button" className="research-secondary research-open-evidence" aria-controls="research-workspace-evidence-panel" onClick={() => openEvidence(message.id)}>查看本轮证据</button>}{message.error && <div className="research-status research-status-warning" style={{ marginTop: 12 }}>{message.error}</div>}</div></article>)}
      </div>
      <section id="research-workspace-evidence-panel" className="research-mobile-evidence-panel" hidden={!isMobile || mobileView !== 'evidence'} role="tabpanel" aria-labelledby="research-workspace-evidence-tab">
        {isMobile && mobileView === 'evidence' && <>{evidenceMessage ? <><div className="research-mobile-evidence-toolbar"><strong>本轮检索证据</strong><label>选择回答 <select aria-label="选择要查看证据的回答" value={evidenceMessage.id} onChange={event => setEvidenceMessageId(event.target.value)}>{assistantMessages.map((message, index) => <option key={message.id} value={message.id}>第 {index + 1} 轮 · {message.role === 'compare' ? '模式对比' : label(message.role)}</option>)}</select></label></div><div data-message-id={evidenceMessage.id}>{renderMobileEvidence(evidenceMessage)}</div><p className="research-muted research-evidence-local-note">证据直接读取本会话已收到的检索结果；切换标签不会重新查询。</p></> : <div className="research-muted">发送问题后，本轮来源片段与检索超图会显示在这里。</div>}</>}
      </section>
      <form className="research-composer" onSubmit={event => { event.preventDefault(); submit() }}><textarea aria-label="输入问题" value={question} onChange={event => setQuestion(event.target.value)} placeholder="例如：比较不同电解液条件下的库仑效率，并定位实验条件与来源。" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit() } }} /><div className="research-composer-actions"><span>Enter 发送 · Shift + Enter 换行</span>{busy ? <button type="button" className="research-secondary" onClick={() => controller.current?.abort()}><Square size={14} />停止</button> : <button className="research-primary" disabled={!question.trim() || missingChannels}><Send size={14} />发送</button>}</div></form>
    </section>
  </div>
}
export default observer(Home)
