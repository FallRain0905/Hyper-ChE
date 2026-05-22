import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  ArrowLeft,
  Bot,
  ChevronDown,
  ChevronRight,
  Database,
  Loader2,
  Network,
  Send,
  User,
} from 'lucide-react'
import RetrievalHyperGraph from '@/components/RetrievalHyperGraph'
import RetrievalInfo from '@/components/RetrievalInfo'
import { SERVER_URL } from '@/utils'

type DemoMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  entities?: any[]
  hyperedges?: any[]
  text_units?: any[]
  themes?: any[]
}

type SseFrame = {
  event: string
  data: string
}

const suggestedQuestions = [
  '比较 Nafion 117、SPEEK/APK、SPI-DH-6O 和 SPTPC-2.59 在 CE、VE、EE、电流密度、交叉渗透、溶胀和成本上的差异。',
  '为什么 SPTPC-2.59 能在 280 mA cm^-2 下保持约 80% EE？多孔膜策略还存在哪些孔径控制和耐久性风险？',
  'B/N 共掺杂的 BMC-C 电极为什么比 MC-C 和 C-C 更适合高电流密度 VRFB？请结合 200 与 500 mA cm^-2 的性能指标解释。',
  '在铁铬液流电池中，Bi@C 和 glycine 如何共同影响 Cr3+/Cr2+ 动力学与析氢副反应？为什么 EDTA 可能反而降低 VE/EE？',
  '比较 VRFB、ICRFB、锌基、有机和多硫化物-溴液流电池的成熟度、成本、能量密度和主要失效机制。',
  '请用 crossover、HER、polarization 和 current density 的例子解释 CE、VE 与 EE 分别反映什么问题。',
]

const getEntityName = (entity: any) => String(entity?.entity_name || entity?.name || entity?.id || '')

const getEdgeMembers = (edge: any): string[] => {
  const raw = edge?.entity_set ?? edge?.id_set ?? edge?.vertices ?? []
  if (Array.isArray(raw)) {
    return raw.map(item => String(item))
  }
  if (typeof raw === 'string') {
    return raw.split('|#|').map(item => item.trim()).filter(Boolean)
  }
  return []
}

const parseSseFrame = (frame: string): SseFrame | null => {
  const lines = frame.split(/\r?\n/)
  let event = 'message'
  const dataLines: string[] = []

  lines.forEach(line => {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  })

  if (!dataLines.length) {
    return null
  }
  return { event, data: dataLines.join('\n') }
}

const CollapsibleRetrievalGraph = ({
  message,
  mode,
}: {
  message: DemoMessage
  mode: string
}) => {
  const [expanded, setExpanded] = useState(false)
  const entityCount = message.entities?.length || 0
  const hyperedgeCount = message.hyperedges?.length || 0
  const hasGraph = entityCount > 0 || hyperedgeCount > 0

  if (!hasGraph) {
    return null
  }

  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white transition-all duration-300">
      <button
        type="button"
        onClick={() => setExpanded(prev => !prev)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-slate-700 transition hover:bg-slate-50"
      >
        <span className="flex items-center gap-2 font-medium">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          本轮对话检索图
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-500">
          {entityCount} entities | {hyperedgeCount} hyperedges
        </span>
      </button>
      {expanded && (
        <div className="border-t border-slate-200 p-3">
          <RetrievalHyperGraph
            entities={message.entities || []}
            hyperedges={message.hyperedges || []}
            themes={message.themes || []}
            height="300px"
            mode={mode}
            graphId={`demo-message-graph-${message.id}`}
          />
        </div>
      )}
    </div>
  )
}

const TryDemo = () => {
  const [messages, setMessages] = useState<DemoMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [mode, setMode] = useState('hyper')
  const [selectedEntity, setSelectedEntity] = useState('')

  const latestGraphMessage = useMemo(
    () => [...messages].reverse().find(message => (message.entities?.length || 0) > 0 || (message.hyperedges?.length || 0) > 0),
    [messages]
  )

  const entities = latestGraphMessage?.entities || []
  const hyperedges = latestGraphMessage?.hyperedges || []

  useEffect(() => {
    const firstEntity = getEntityName(entities[0])
    if (firstEntity && !entities.some(entity => getEntityName(entity) === selectedEntity)) {
      setSelectedEntity(firstEntity)
    }
    if (!entities.length) {
      setSelectedEntity('')
    }
  }, [entities, selectedEntity])

  const selectedEntityData = useMemo(
    () => entities.find(entity => getEntityName(entity) === selectedEntity),
    [entities, selectedEntity]
  )

  const connectedHyperedges = useMemo(() => {
    if (!selectedEntity) {
      return hyperedges
    }
    return hyperedges.filter(edge => getEdgeMembers(edge).includes(selectedEntity))
  }, [hyperedges, selectedEntity])

  const visualEntities = useMemo(() => {
    if (!selectedEntity) {
      return entities
    }
    const memberNames = new Set<string>([selectedEntity])
    connectedHyperedges.forEach(edge => getEdgeMembers(edge).forEach(name => memberNames.add(name)))
    const existing = entities.filter(entity => memberNames.has(getEntityName(entity)))
    const existingNames = new Set(existing.map(getEntityName))
    const missing = [...memberNames]
      .filter(name => !existingNames.has(name))
      .map(name => ({ entity_name: name, entity_type: 'UNKNOWN', description: 'Entity referenced by a retrieved hyperedge.' }))
    return [...existing, ...missing]
  }, [connectedHyperedges, entities, selectedEntity])

  const updateAssistantMessage = (id: string, patch: Partial<DemoMessage>) => {
    setMessages(prev => prev.map(message => (message.id === id ? { ...message, ...patch } : message)))
  }

  const queryPayload = (question: string, onlyNeedContext = false) => ({
    question,
    mode,
    top_k: 60,
    max_token_for_text_unit: 1600,
    max_token_for_entity_context: 300,
    max_token_for_relation_context: 1600,
    only_need_context: onlyNeedContext,
    response_type: 'Multiple Paragraphs',
  })

  const loadGraphContext = async (question: string, assistantId: string) => {
    try {
      const response = await fetch(`${SERVER_URL}/public/demo/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queryPayload(question, true)),
      })
      const data = await response.json()
      if (data?.success) {
        updateAssistantMessage(assistantId, {
          entities: data.entities || [],
          hyperedges: data.hyperedges || [],
          text_units: data.text_units || [],
          themes: data.themes || [],
        })
      }
    } catch (error) {
      console.warn('Failed to load demo graph context', error)
    }
  }

  const runJsonQuery = async (question: string, assistantId: string) => {
    const response = await fetch(`${SERVER_URL}/public/demo/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(queryPayload(question)),
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    if (!data.success) {
      throw new Error(data.message || 'Demo query failed')
    }

    updateAssistantMessage(assistantId, {
      content: `${data.response || 'No response content'}\n\n---\n*Public Demo - ${mode === 'graph' ? 'Graph-RAG' : 'Hyper-RAG'}*`,
      entities: data.entities || [],
      hyperedges: data.hyperedges || [],
      text_units: data.text_units || [],
      themes: data.themes || [],
    })
  }

  const runStreamQuery = async (question: string, assistantId: string) => {
    const response = await fetch(`${SERVER_URL}/public/demo/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(queryPayload(question)),
    })

    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let streamedText = ''

    let streamDone = false
    while (!streamDone) {
      const { value, done } = await reader.read()
      if (done) {
        streamDone = true
        continue
      }
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\n\n/)
      buffer = frames.pop() || ''

      for (const rawFrame of frames) {
        const frame = parseSseFrame(rawFrame)
        if (!frame) {
          continue
        }
        const data = JSON.parse(frame.data)
        if (frame.event === 'token') {
          streamedText += data.text || ''
          updateAssistantMessage(assistantId, { content: streamedText || '正在生成回答...' })
        }
        if (frame.event === 'error') {
          throw new Error(data.message || 'Streaming query failed')
        }
      }
    }

    updateAssistantMessage(assistantId, {
      content: `${streamedText || 'No response content'}\n\n---\n*Public Demo - Hyper-RAG · streaming*`,
    })
    await loadGraphContext(question, assistantId)
  }

  const ask = async (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || isLoading) {
      return
    }

    const userMessage: DemoMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
    }
    const loadingMessage: DemoMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: mode === 'hyper' ? '正在流式生成回答...' : '正在从公开示例库检索并组织回答...',
    }

    setMessages(prev => [...prev, userMessage, loadingMessage])
    setInputValue('')
    setIsLoading(true)

    try {
      if (mode === 'hyper') {
        await runStreamQuery(trimmed, loadingMessage.id)
      } else {
        await runJsonQuery(trimmed, loadingMessage.id)
      }
    } catch (error: any) {
      try {
        await runJsonQuery(trimmed, loadingMessage.id)
      } catch (fallbackError: any) {
        updateAssistantMessage(loadingMessage.id, {
          content: `公开示例查询失败：${fallbackError?.message || error?.message || 'Unknown error'}`,
        })
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleSubmit = () => ask(inputValue)

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-[#F8FAFC] text-slate-950">
      <div className="pointer-events-none absolute left-[-120px] top-24 h-72 w-72 rounded-full bg-teal-100/70 blur-3xl" />
      <div className="pointer-events-none absolute right-[-140px] top-72 h-80 w-80 rounded-full bg-blue-100/70 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-120px] left-1/3 h-72 w-72 rounded-full bg-violet-100/60 blur-3xl" />

      <header className="relative z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <Link to="/" className="flex items-center gap-3 text-sm font-medium text-slate-700 transition hover:text-teal-700">
            <ArrowLeft size={16} />
            返回首页
          </Link>
          <Link to="/app/Hyper/chat" className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-teal-800">
            登录后进入工作台
          </Link>
        </div>
      </header>

      <main className="relative z-10 mx-auto grid min-h-[calc(100vh-64px)] w-full max-w-7xl gap-5 px-6 py-6 lg:grid-cols-[0.6fr_0.4fr]">
        <section className="flex min-h-[680px] flex-col rounded-lg border border-slate-200 bg-white/95 shadow-sm backdrop-blur">
          <div className="border-b border-slate-200 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-teal-700">
                  <Database size={16} />
                  公共示例知识库：example
                </div>
                <h1 className="mt-2 text-2xl font-semibold text-slate-950">试用 HyperChE 问答</h1>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  该页面固定使用液流电池示例库，开放流式问答、消息内检索图和右侧实体邻域超图，不支持上传、删除或修改知识库。
                </p>
              </div>
              <div className="flex rounded-lg bg-slate-100 p-1 text-sm">
                {[
                  ['hyper', 'Hyper-RAG'],
                  ['graph', 'Graph-RAG'],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    className={`rounded-md px-3 py-2 font-medium transition ${mode === value ? 'bg-white text-teal-800 shadow-sm' : 'text-slate-600 hover:text-teal-700'}`}
                    onClick={() => setMode(value)}
                    type="button"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {suggestedQuestions.map(question => (
                <button
                  key={question}
                  type="button"
                  onClick={() => ask(question)}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-teal-200 hover:bg-white hover:text-teal-700"
                  disabled={isLoading}
                >
                  {question}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {messages.length === 0 ? (
              <div className="flex h-full min-h-[320px] items-center justify-center">
                <div className="max-w-md text-center">
                  <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-teal-50 text-teal-700 shadow-[0_0_0_10px_rgba(15,118,110,0.06)]">
                    <Bot className="h-8 w-8 animate-pulse" />
                  </div>
                  <h2 className="text-lg font-semibold text-slate-950">选择一个示例问题，或直接输入你的问题</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-500">
                    Hyper-RAG 模式会流式输出回答；回答完成后会加载本轮检索到的实体、超边和右侧实体邻域图。
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-5">
                {messages.map(message => (
                  <div key={message.id} className="flex gap-3">
                    <div className={`mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${message.role === 'user' ? 'bg-blue-50 text-blue-700' : 'bg-teal-50 text-teal-700'}`}>
                      {message.role === 'user' ? <User size={18} /> : <Bot size={18} />}
                    </div>
                    <div className={`min-w-0 flex-1 rounded-lg border p-4 shadow-sm transition ${message.role === 'user' ? 'border-blue-100 bg-blue-50' : 'border-slate-200 bg-slate-50'}`}>
                      <div className="prose prose-sm max-w-none">
                        <ReactMarkdown>{message.content}</ReactMarkdown>
                      </div>
                      {message.role === 'assistant' && (
                        <div className="mt-4">
                          <RetrievalInfo
                            entities={message.entities || []}
                            hyperedges={message.hyperedges || []}
                            textUnits={message.text_units || []}
                            themes={message.themes || []}
                            mode={mode}
                          />
                          <CollapsibleRetrievalGraph message={message} mode={mode} />
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-slate-200 bg-white/90 p-4">
            <div className="flex gap-3">
              <textarea
                value={inputValue}
                onChange={event => setInputValue(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    handleSubmit()
                  }
                }}
                className="min-h-[48px] flex-1 resize-none rounded-lg border border-slate-200 px-3 py-3 text-sm outline-none transition focus:border-teal-600 focus:ring-4 focus:ring-teal-50"
                placeholder="询问这个化工示例库..."
                disabled={isLoading}
              />
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!inputValue.trim() || isLoading}
                className="flex h-12 w-12 items-center justify-center rounded-lg bg-teal-700 text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-teal-800 disabled:opacity-60"
              >
                {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </button>
            </div>
          </div>
        </section>

        <aside className="flex max-h-none min-h-[620px] flex-col rounded-lg border border-slate-200 bg-white/95 shadow-sm backdrop-blur lg:sticky lg:top-20 lg:max-h-[calc(100vh-96px)]">
          <div className="border-b border-slate-200 p-5">
            <div className="flex items-center gap-2 text-lg font-semibold text-slate-950">
              <Network size={18} />
              实体邻域超图可视化
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              这里模拟工作台的超图可视化页面：从下拉框选择一个实体，查看它参与的超边及相关实体邻域。
            </p>
          </div>

          <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr] gap-4 p-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <label className="mb-2 block text-xs font-medium text-slate-600">选择实体</label>
              <select
                value={selectedEntity}
                onChange={event => setSelectedEntity(event.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-teal-600 focus:ring-4 focus:ring-teal-50"
                disabled={!entities.length}
              >
                {entities.length ? (
                  entities.slice(0, 120).map(entity => {
                    const name = getEntityName(entity)
                    const type = entity.entity_type || entity.type || 'UNKNOWN'
                    return (
                      <option key={name} value={name}>
                        {name} · {type}
                      </option>
                    )
                  })
                ) : (
                  <option value="">提交问题后显示实体</option>
                )}
              </select>
            </div>

            <div className="min-h-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
              {latestGraphMessage ? (
                <div className="flex h-full flex-col">
                  <div className="border-b border-slate-200 p-3">
                    <div className="truncate text-sm font-semibold text-slate-950">
                      {selectedEntity || '完整检索图'}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {connectedHyperedges.length} connected hyperedges | {visualEntities.length} visible entities
                    </div>
                    {selectedEntityData?.description && (
                      <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">
                        {String(selectedEntityData.description).split('<SEP>').slice(0, 2).join('; ')}
                      </p>
                    )}
                  </div>
                  <div className="h-[360px] min-h-0 p-3">
                    <RetrievalHyperGraph
                      entities={visualEntities}
                      hyperedges={selectedEntity ? connectedHyperedges : hyperedges}
                      themes={latestGraphMessage.themes || []}
                      height="100%"
                      mode={mode}
                      graphId={`public-demo-entity-neighborhood-${selectedEntity || 'all'}`}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex h-[360px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center">
                  <div>
                    <Network className="mx-auto mb-3 h-12 w-12 animate-pulse text-slate-300" />
                    <div className="text-sm font-medium text-slate-700">暂无可视化数据</div>
                    <p className="mt-2 text-xs leading-5 text-slate-500">
                      提交问题后，右侧会展示可选择实体的邻域超图；消息中也可以展开查看本轮检索图。
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default TryDemo
