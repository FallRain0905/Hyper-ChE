import React, { useMemo, useRef, useCallback, useEffect, useState } from 'react'
import { Graphin } from '@antv/graphin'
import type { Graph as G6Graph, GraphOptions } from '@antv/g6'
import { useTranslation } from 'react-i18next'

const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char] || char))
const colors = [
  '#F6BD16',
  '#00C9C9',
  '#F08F56',
  '#D580FF',
  '#FF3D00',
  '#16f69c',
  '#004ac9',
  '#f056d1',
  '#a680ff',
  '#c8ff00'
]

//  colors 加深
const entityTypeColors = {
  PERSON: '#00C9C9',
  CONCEPT: '#a68fff',
  ORGANIZATION: '#F08F56',
  LOCATION: '#16f69c',
  EVENT: '#004ac9',
  PRODUCT: '#f056d1',
  Theme: '#13c2c2' // 主题节点的颜色
}

// Project Graphin/G6 component, with safe details and responsive controls.
export interface RetrievalHyperGraphProps {
  entities?: Array<Record<string, any>>
  hyperedges?: Array<Record<string, any>>
  themes?: Array<Record<string, any>>
  height?: string
  width?: string
  showTooltip?: boolean
  containerStyle?: React.CSSProperties
  graphId?: string
  mode?: 'hyper' | 'graph'
  displayLabels?: Record<string, string>
  graphRef?: React.Ref<G6Graph | null>
  onInit?: (graph: G6Graph) => void
  onReady?: (graph: G6Graph) => void
  onDestroy?: () => void
  onNodeClick?: (id: string, graph: G6Graph, event: any) => void
  selectedHyperedgeIds?: string[]
}

const RetrievalHyperGraph = ({
  entities = [],
  hyperedges = [],
  themes = [], // 新增themes属性
  height = '300px',
  width = '100%',
  showTooltip = true,
  containerStyle = {},
  graphId = 'retrieval-hypergraph',
  mode = 'hyper', // 新增mode参数，默认为hyper模式
  displayLabels,
  graphRef,
  onInit,
  onReady,
  onDestroy,
  onNodeClick,
  selectedHyperedgeIds
}: RetrievalHyperGraphProps) => {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const liveGraph = useRef<G6Graph | null>(null)
  const refreshLabels = useCallback((graph: G6Graph) => {
    try {
      const zoom = graph.getZoom()
      if (!(zoom > 0)) return
      graph.updateNodeData(graph.getNodeData().map(node => ({ id: node.id, style: { labelFontSize: Math.min(44, 13 / zoom) } })))
      graph.draw().catch(() => undefined)
    } catch { /* The viewport can be absent during initialization or disposal. */ }
  }, [])
  const [ready, setReady] = useState(false)
  const [selected, setSelected] = useState('')
  const [selectedEdge, setSelectedEdge] = useState('')
  useEffect(() => {
    const graph = liveGraph.current
    const host = containerRef.current
    if (!ready || !graph || !host) return
    let frame = 0
    const resize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const canvasHost = graph.getCanvas()?.getContainer()
        const size = canvasHost ? [canvasHost.clientWidth, canvasHost.clientHeight] : null
        if (!size || !size[0] || !size[1]) return
        const old = graph.getSize()
        if (Math.abs(old[0] - size[0]) < 2 && Math.abs(old[1] - size[1]) < 2) return
        graph.resize(size[0], size[1])
        graph.fitView({ when: 'always' }, false).then(() => refreshLabels(graph)).catch(() => undefined)
      })
    }
    const observer = new ResizeObserver(resize)
    observer.observe(host)
    resize()
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [ready, refreshLabels])
  // Graphin initializes once; refs keep host callbacks current across rerenders.
  const hostCallbacks = useRef({ onInit, onReady, onDestroy, onNodeClick })
  hostCallbacks.current = { onInit, onReady, onDestroy, onNodeClick }
  const boundNodeClick = useRef<{ graph: G6Graph; listener: (event: any) => void; transform: () => void } | null>(null)
  const handleInit = useCallback((graph: G6Graph) => {
    const listener = (event: any) => {
      const id = event.target?.id
      if (id !== undefined) { setSelected(String(id)); setSelectedEdge(''); hostCallbacks.current.onNodeClick?.(String(id), graph, event) }
    }
    liveGraph.current = graph
    graph.on('node:click', listener)
    const transform = () => refreshLabels(graph)
    graph.on('aftertransform', transform)
    boundNodeClick.current = { graph, listener, transform }
    hostCallbacks.current.onInit?.(graph)
  }, [refreshLabels])
  const handleReady = useCallback((graph: G6Graph) => {
    setReady(true)
    graph.setOptions({ padding: [30, 36, 36, 36] })
    graph.fitView({ when: 'always' }, false).then(() => refreshLabels(graph)).catch(() => undefined)
    hostCallbacks.current.onReady?.(graph)
  }, [refreshLabels])
  const handleDestroy = useCallback(() => {
    const bound = boundNodeClick.current
    if (bound) {
      bound.graph.off('node:click', bound.listener)
      bound.graph.off('aftertransform', bound.transform)
    }
    boundNodeClick.current = null
    liveGraph.current = null
    setReady(false)
    hostCallbacks.current.onDestroy?.()
  }, [])
  const edgesName = mode === 'hyper' ? t('retrieval.hyperedge_count') : t('retrieval.edge_count')
  // 转换数据格式为HyperGraph组件需要的格式
  const convertedData = useMemo(() => {
    // 如果没有数据，返回空
    if (!entities.length && !hyperedges.length && !themes.length) {
      return null
    }

    const vertices: Record<string, any> = {}
    const edges: Record<string, any> = {}

    // 处理实体数据
    entities.forEach(entity => {
      const entityName = String(entity.entity_name || entity.name || entity.id || `Entity_${entities.indexOf(entity)}`)
      vertices[entityName] = {
        ...entity,
        entity_type: String(entity.entity_type || t('retrieval.unknown')),
        description: String(entity.description || ''),
        label: String(entity.entity_name || entity.name || entity.id || ''),
        nodeType: 'entity' // 标识为实体节点
      }
    })

    // 处理主题数据（主题节点来自主题超图索引）
    themes.forEach(theme => {
      const themeName = String(theme.theme_name || theme.id || `Theme_${themes.indexOf(theme)}`)
      vertices[themeName] = {
        ...theme,
        entity_type: 'Theme',
        description: String(theme.description || ''),
        label: String(theme.theme_name || theme.id || ''),
        nodeType: 'theme', // 标识为主题节点
        keywords: theme.keywords || []
      }
    })

    // 处理超边数据
    hyperedges.forEach((edge, index) => {
      // Optional presentation filter; the host keeps the complete source dataset.
      if (selectedHyperedgeIds && !selectedHyperedgeIds.includes(String(edge.id || edge.efu_id || ''))) return
      // Distinct condition/evidence edges retain their identity when members match.
      const rawMembers = edge.entity_set ?? edge.id_set ?? edge.vertices ?? []
      const entityNames = Array.isArray(rawMembers) ? rawMembers.map(String) : String(rawMembers).split('|#|').filter(Boolean)
      if (!entityNames.length) return
      const edgeKey = String(edge.id || edge.efu_id || 'edge') + ':' + index

      // 确保超边中的实体也在vertices中
      entityNames.forEach(entityName => {
        if (!vertices[entityName]) {
          vertices[entityName] = {
            entity_type: t('retrieval.unknown'),
            description: `${t('retrieval.entity_from_hyperedge')}: ${entityName}`
          }
        }
      })

      edges[edgeKey] = {
        keywords: String(edge.keywords || edge.description || ''),
        description: String(edge.description || ''),
        weight: edge.weight || 1,
        ...edge,
        memberIds: entityNames
      }
    })

    return { vertices, edges }
  }, [entities, hyperedges, themes, t, selectedHyperedgeIds])

  const options = useMemo<GraphOptions>(() => {
    const hyperData = {
      nodes: [] as any[],
      edges: [] as any[]
    }
    const plugins: any[] = []

    if (convertedData) {
      // 添加顶点
      for (const key in convertedData.vertices) {
        hyperData.nodes.push({
          ...convertedData.vertices[key],
          id: key,
          type: 'circle',
          label: String(key) // 确保label是字符串
        })
      }

      if (mode === 'graph') {
        // graph模式：设置标准边格式，不使用plugins
        const edgeKeys = Object.keys(convertedData.edges)
        for (let i = 0; i < edgeKeys.length; i++) {
          const key = edgeKeys[i]
          const nodes = convertedData.edges[key].memberIds

          // 为每对节点创建边
          for (let j = 0; j < nodes.length; j++) {
            for (let k = j + 1; k < nodes.length; k++) {
              hyperData.edges.push({
                ...convertedData.edges[key],
                source: nodes[j],
                target: nodes[k],
                type: 'line'
              })
            }
          }
        }
      } else {
        // hyper模式：使用原有的bubble-sets插件
        // 创建样式函数
        const createStyle = baseColor => ({
          fill: baseColor,
          stroke: baseColor,
          labelFill: '#fff',
          labelPadding: 2,
          labelBackgroundFill: baseColor,
          labelBackgroundRadius: 5,
          labelPlacement: 'center',
          labelAutoRotate: false,
          // bubblesets配置
          maxRoutingIterations: 100,
          maxMarchingIterations: 20,
          pixelGroup: 4,
          edgeR0: 10,
          edgeR1: 60,
          nodeR0: 15,
          nodeR1: 50,
          morphBuffer: 10,
          threshold: 4,
          memberInfluenceFactor: 1,
          edgeInfluenceFactor: 4,
          nonMemberInfluenceFactor: -0.8,
          virtualEdges: true
        })

        // 添加超边
        const edgeKeys = Object.keys(convertedData.edges)
        for (let i = 0; i < edgeKeys.length; i++) {
          const key = edgeKeys[i]
          const edge = convertedData.edges[key]
          const nodes = convertedData.edges[key].memberIds

          plugins.push({
            key: `bubble-sets-${key}`,
            type: 'bubble-sets',
            members: nodes,
            // labelText: String(edge.keywords || ''), // 确保labelText是字符串
            ...createStyle(colors[i % colors.length])
          })
        }
      }

      // 添加tooltip插件
      if (showTooltip) {
        plugins.push({
          type: 'tooltip',
          getContent: (e, items) => {
            let result = ''
            items.forEach(item => {
              result += `<h4>${escapeHtml(item.id)}</h4>`
              if (item.entity_type) {
                result += `<p><strong>${t('retrieval.entity_type')}:</strong> ${escapeHtml(item.entity_type)}</p>`
              }
              if (item.description) {
                const desc = escapeHtml(item.description)
                result += `<p><strong>${t('retrieval.description')}:</strong> ${desc
                  .split('<SEP>')
                  .slice(0, 2)
                  .join('; ')}</p>`
              }
            })
            return result
          }
        })
      }
    }

    return {
      autoResize: true,
      data: hyperData,
      node: {
        palette: { field: 'cluster' },
        style: {
          size: mode === 'graph' ? 20 : 25,
          labelText: d => displayLabels?.[String(d.id)] || String(d.display_name || d.canonical_name || d.id).replace(/^[^:]+:/, '').replace(/_/g, ' '),
          labelFontFamily: 'Segoe UI, Microsoft YaHei, sans-serif',
          labelFontSize: 13,
          labelBackground: true,
          labelBackgroundFill: '#fffefa',
          labelPadding: 2,
          labelFill: '#243a2c',
          fill: d => {
            // 根据entity_type设置不同颜色
            if (d.entity_type) {
              return entityTypeColors[String(d.entity_type)] || '#8566CC'
            }
            // 默认颜色
            return '#8566CC'
          }
        }
      },
      edge: {
        style: {
          stroke: '#a68fff', // 边的颜色
          lineWidth: 3
        }
      },
      animate: false,
      behaviors: ['zoom-canvas', 'drag-canvas', 'drag-element'],
      autoFit: { type: 'view' as const },
      layout: {
        type: 'force-atlas2',
        // clustering: true,
        preventOverlap: true,
        // nodeClusterBy: 'entity_type',
        kr: mode === 'graph' ? 5 : 80,
        gravity: 20,
        linkDistance: 10
      },
      plugins: mode === 'graph' ? (showTooltip ? plugins : []) : plugins
    }
  }, [convertedData, showTooltip, mode, t, displayLabels])


  const selectedEntity = entities.find(entity => String(entity.entity_name || entity.name || entity.id) === selected)
  const edgeRecords = convertedData ? Object.entries(convertedData.edges) : []
  const selectedEdgeRecord = selectedEdge ? convertedData?.edges[selectedEdge] : null
  const linkedEdges = selected ? edgeRecords.filter(([, edge]) => edge.memberIds.includes(selected)) : []
  const highlightMembers = selectedEdgeRecord?.memberIds || (selected ? [...new Set(linkedEdges.flatMap(([, edge]) => edge.memberIds))] : [])
  useEffect(() => {
    const graph = liveGraph.current
    if (!ready || !graph) return
    graph.updateNodeData(graph.getNodeData().map(node => ({ id: node.id, style: { opacity: highlightMembers.length && !highlightMembers.includes(String(node.id)) ? .25 : 1, lineWidth: String(node.id) === selected ? 3 : 1, stroke: String(node.id) === selected ? '#285a45' : '#fff' } })))
    const activeKeys = new Set(selectedEdge ? [selectedEdge] : linkedEdges.map(([key]) => key))
    graph.setPlugins(graph.getPlugins().map(plugin => typeof plugin === 'object' && plugin.type === 'bubble-sets' ? {
      ...plugin,
      fillOpacity: !activeKeys.size ? .16 : activeKeys.has(String(plugin.key).replace(/^bubble-sets-/, '')) ? .24 : .025,
      strokeOpacity: !activeKeys.size ? .5 : activeKeys.has(String(plugin.key).replace(/^bubble-sets-/, '')) ? .85 : .12,
    } : plugin))
    graph.draw().catch(() => undefined)
  }, [ready, selected, selectedEdge, convertedData])

  if (!convertedData || (!entities.length && !hyperedges.length && !themes.length)) return null
  return <div ref={containerRef} className="research-graph-shell" style={{ width, ...containerStyle }}>
    <div className="research-graph-controls">
      <span className="research-muted" style={{ marginRight: 'auto' }}>{Object.keys(convertedData.vertices).length} 个节点 · {edgeRecords.length} 条{mode === 'graph' ? '关系' : '超边'}</span>
      <button type="button" onClick={() => liveGraph.current?.zoomBy(1.2, false)} aria-label="放大超图">+</button>
      <button type="button" onClick={() => liveGraph.current?.zoomBy(1 / 1.2, false)} aria-label="缩小超图">−</button>
      <button type="button" onClick={() => { setSelected(''); setSelectedEdge(''); liveGraph.current?.fitView({ when: 'always' }, false) }}>重置视图</button>
    </div>
    <Graphin ref={graphRef} onInit={handleInit} onReady={handleReady} onDestroy={handleDestroy} options={options} id={graphId} style={{ width: '100%', height, minHeight: 260 }} />
    <div className="research-graph-details">
      <label>选择超边 <select aria-label="选择超边查看成员" value={selectedEdge} onChange={event => { setSelectedEdge(event.target.value); setSelected('') }} style={{ maxWidth: '100%', border: '1px solid var(--rule)', borderRadius: 5, padding: 4 }}>
        <option value="">全部超边</option>{edgeRecords.map(([key, edge], index) => <option key={key} value={key}>{index + 1}. {String(edge.keywords || edge.description || edge.id || key).slice(0, 90)}</option>)}
      </select></label>
      {selected && <div style={{ marginTop: 10 }}><strong>{selectedEntity?.label || selected}</strong><div className="research-mono">{selected}</div><p>{String(selectedEntity?.description || '')}</p><span className="research-muted">关联 {linkedEdges.length} 条超边；成员已突出显示。</span></div>}
      {selectedEdgeRecord && <div style={{ marginTop: 10 }}><strong>{String(selectedEdgeRecord.keywords || '超边详情')}</strong><p>{String(selectedEdgeRecord.description || '')}</p><div>成员：{selectedEdgeRecord.memberIds.join('、')}</div><div className="research-mono">来源：{(selectedEdgeRecord.source_chunk_ids || [selectedEdgeRecord.source_chunk_id || selectedEdgeRecord.source_id]).filter(Boolean).join(' · ')}</div>{(selectedEdgeRecord.source_spans || [selectedEdgeRecord.source_span]).filter(Boolean).map((span, index) => <pre key={index} style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{typeof span === 'string' ? span : JSON.stringify(span)}</pre>)}</div>}
      {!selected && !selectedEdge && <p className="research-muted" style={{ marginTop: 8 }}>点击节点查看关系，拖动平移，滚轮缩放。彩色包络表示多实体属于同一条超边。</p>}
    </div>
  </div>
}

export default RetrievalHyperGraph
