import { lazy, Suspense, useState } from 'react'
import type { QueryResult } from '@/services/retrieval'
const RetrievalHyperGraph = lazy(() => import('@/components/RetrievalHyperGraph'))

function members(edge: any): string[] {
  const value = edge.entity_set ?? edge.id_set ?? edge.vertices ?? []
  return Array.isArray(value) ? value.map(String) : String(value).split('|#|').filter(Boolean)
}

export default function RetrievalEvidence({ result, mode = 'hyper', graphId }: { result: QueryResult; mode?: string; graphId: string }) {
  const [showGraph, setShowGraph] = useState(false)
  const entities = result.entities || []
  const edges = result.hyperedges || []
  const chunks = result.text_units || []
  const meta = result.retrieval_meta || {}
  if (!entities.length && !edges.length && !chunks.length && !Object.keys(meta).length) return null
  return <section className="research-evidence" aria-label="本轮检索证据">
    <div className="research-evidence-summary"><strong>本轮证据</strong><span>{chunks.length} 个片段</span><span>{edges.length} 条{mode === 'graph' ? '关系' : '超边'}</span><span>{entities.length} 个实体</span></div>
    {Object.keys(meta).length > 0 && <div className="research-muted" style={{ marginTop: 6 }}>
      {String(meta.profile || meta.retrieval_profile || '自动匹配知识库')} · {meta.rerank_enabled === false ? '未启用结构重排' : meta.rerank_enabled === true ? '结构重排已启用' : '证据与回答来自同一次查询'}
      {(meta.evidence_top_k || meta.returned_evidence_count) && <span> · top-{meta.evidence_top_k || meta.returned_evidence_count}</span>}
    </div>}
    {chunks.length > 0 && <details><summary>查看来源片段</summary>{chunks.map((chunk, index) => <article key={chunk.id || chunk.chunk_id || index} className="research-evidence-card"><strong>[{index + 1}] {String(chunk.source_name || chunk.file_path || chunk.source || chunk.source_id || chunk.id || chunk.chunk_id || '原始文档')}</strong><div className="research-mono research-muted">{String(chunk.chunk_id || chunk.id || '')}</div><pre>{String(chunk.content || chunk.text || '')}</pre></article>)}</details>}
    {edges.length > 0 && <details><summary>查看关系与成员</summary>{edges.map((edge, index) => <article className="research-evidence-card" key={edge.id || edge.efu_id || index}><strong>{String(edge.keywords || `超边 ${index + 1}`)}</strong><p>{String(edge.description || '')}</p><div className="research-muted">成员：{members(edge).join('、')}</div>{edge.source_span && <div className="research-mono">来源：{typeof edge.source_span === 'string' ? edge.source_span : JSON.stringify(edge.source_span)}</div>}</article>)}</details>}
    {(entities.length > 0 || edges.length > 0) && <><button type="button" className="research-secondary" aria-expanded={showGraph} onClick={() => setShowGraph(value => !value)} style={{ margin: '8px 0' }}>{showGraph ? '收起检索超图' : '查看本轮检索超图'}</button>{showGraph && <Suspense fallback={<p className="research-muted">正在加载超图组件…</p>}><RetrievalHyperGraph entities={entities} hyperedges={edges} themes={result.themes || []} mode={mode === 'graph' ? 'graph' : 'hyper'} graphId={graphId} height="430px" /></Suspense>}</>}
  </section>
}
