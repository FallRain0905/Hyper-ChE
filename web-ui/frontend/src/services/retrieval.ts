import { SERVER_URL } from '@/utils'

export type RetrievalMeta = Record<string, any>
export type QueryResult = {
  success?: boolean
  response?: string
  message?: string
  error?: string
  database?: string
  mode?: string
  entities?: any[]
  hyperedges?: any[]
  text_units?: any[]
  themes?: any[]
  retrieval_meta?: RetrievalMeta
  rag_system?: string
}
export type QueryPayload = {
  question: string
  mode: string
  database?: string
  top_k: number
  evidence_top_k: number
  retrieval_profile: 'auto'
  max_token_for_text_unit: number
  max_token_for_entity_context: number
  max_token_for_relation_context: number
  only_need_context: boolean
  response_type: string
}

export function buildQueryPayload(question: string, mode: string, database?: string): QueryPayload {
  return {
    question,
    mode,
    ...(database ? { database } : {}),
    top_k: 60,
    evidence_top_k: 5,
    retrieval_profile: 'auto',
    max_token_for_text_unit: 1600,
    max_token_for_entity_context: 300,
    max_token_for_relation_context: 1600,
    only_need_context: false,
    response_type: 'Multiple Paragraphs',
  }
}

function errorMessage(data: any, fallback: string): string {
  if (Array.isArray(data?.detail)) return data.detail.map((item: any) => item.msg).join('；') || fallback
  return String(data?.detail?.message || data?.detail || data?.message || fallback)
}

export async function queryJson(payload: QueryPayload, publicDemo = false, signal?: AbortSignal): Promise<QueryResult> {
  const response = await fetch(`${SERVER_URL}${publicDemo ? '/public/demo/query' : '/hyperrag/query'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.success === false) throw new Error(errorMessage(data, `查询失败（${response.status}）`))
  return data
}

export type QueryCallbacks = {
  onRetrieval: (result: QueryResult) => void
  onToken: (text: string) => void
  onDone?: (result: QueryResult) => void
}

// One request owns the evidence and answer. A partial stream is never silently retried.
export async function queryStream(payload: QueryPayload, callbacks: QueryCallbacks, publicDemo = false, signal?: AbortSignal): Promise<QueryResult> {
  const response = await fetch(`${SERVER_URL}${publicDemo ? '/public/demo/query/stream' : '/hyperrag/query/stream'}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(errorMessage(data, `查询失败（${response.status}）`))
  }
  if (!response.body) throw new Error('浏览器无法读取流式回答，请稍后重试')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let text = ''
  let completed = false
  let result: QueryResult = {}
  const consume = (frame: string) => {
    const lines = frame.split(/\r?\n/)
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const body = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    if (!body) return
    const data = JSON.parse(body)
    if (event === 'retrieval') {
      result = { ...result, ...data }
      callbacks.onRetrieval(result)
    } else if (event === 'token') {
      text += String(data.text || '')
      callbacks.onToken(text)
    } else if (event === 'done') {
      completed = true
      result = { ...result, ...data, response: data.response || text || result.response, success: true }
      callbacks.onDone?.(result)
    } else if (event === 'error') {
      throw new Error(errorMessage(data, '回答生成中断，请保留证据后重试'))
    }
  }
  try {
    let streamOpen = true
    while (streamOpen) {
      const chunk = await reader.read()
      buffer += decoder.decode(chunk.value, { stream: !chunk.done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      frames.forEach(consume)
      streamOpen = !chunk.done
    }
    if (buffer.trim()) consume(buffer)
    if (!completed) throw new Error('连接提前结束，回答可能不完整；本轮证据已保留')
    return result
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
