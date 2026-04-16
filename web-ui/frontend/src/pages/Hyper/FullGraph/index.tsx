import { useState, useEffect, useMemo, useRef } from 'react';
import { Card, Spin, Button, Statistic, message, Select } from 'antd';
import { useTranslation } from 'react-i18next';
import { observer } from 'mobx-react';
import { storeGlobalUser } from '../../../store/globalUser';
import DatabaseSelector from '../../../components/DatabaseSelector';
import { DatabaseOutlined, DownloadOutlined, SyncOutlined } from '@ant-design/icons';
import { SERVER_URL } from '../../../utils';
import { Graphin } from '@antv/graphin';

// 节点颜色数组
const nodeColors = [
  '#F6BD16',
  '#00C9C9',
  '#F08F56',
  '#FFA726',
  '#FA8C16',
  '#722ED1',
  '#a680ff',
  '#c8ff00',
  '#ffeb3b',
  '#ff6b6b',
  '#6366f1'
];

// 超边颜色数组
const bubbleSetColors = [
  '#F6BD16',
  '#00C9C9',
  '#F08F56',
  '#FFA726',
  '#FA8C16',
  '#722ED1',
  '#a680ff',
  '#c8ff00',
  '#ffeb3b',
  '#ff6b6b',
  '#6366f1'
];

// 基于名称哈希的颜色分配
const getNodeColorByName = (name: string): string => {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i);
    hash = hash & hash;
  }
  return nodeColors[Math.abs(hash) % nodeColors.length];
};

const entityTypeColors = {
  'PERSON': '#00C9C9',
  'CONCEPT': '#a68fff',
  'ORGANIZATION': '#F08F56',
  'LOCATION': '#FFA726',
  'EVENT': '#FA8C16',
  'PRODUCT': '#722ED1',
  'default': '#8566CC'
};

const FullGraphPage = observer(() => {
  const { t } = useTranslation();
  const [vertices, setVertices] = useState<any[]>([]);
  const [hyperedges, setHyperedges] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphMode, setGraphMode] = useState('hyperedges');
  const isMountedRef = useRef(true);
  const loadingRef = useRef(false);
  const lastLoadedDbRef = useRef<string | null>(null);

  const loadData = async (dbName: string) => {
    console.log('[FullGraph] loadData 被调用, dbName:', dbName);

    if (!isMountedRef.current || !dbName) {
      console.log('[FullGraph] loadData 被跳过 - isMountedRef:', isMountedRef.current, ', dbName:', dbName);
      return;
    }

    // 防止重复加载同一个数据库（正在加载）
    if (loadingRef.current) {
      console.log('[FullGraph] 跳过重复加载（正在加载）:', dbName);
      return;
    }

    console.log('[FullGraph] 开始加载数据:', dbName);
    // 在开始加载时立即设置标志，防止 useEffect 在加载期间再次触发
    lastLoadedDbRef.current = dbName;
    loadingRef.current = true;
    setLoading(true);
    setError(null);

    try {
      // 首先检查数据库是否存在
      const statusUrl = `${SERVER_URL}/database/status?database=${encodeURIComponent(dbName)}`;
      console.log('[FullGraph] 检查数据库状态:', statusUrl);

      const statusRes = await fetch(statusUrl);
      if (!statusRes.ok) {
        throw new Error('无法获取数据库状态');
      }

      const statusData = await statusRes.json();
      console.log('[FullGraph] 数据库状态:', statusData);

      if (!statusData.exists) {
        console.log('[FullGraph] 数据库不存在，清空数据');
        if (isMountedRef.current) {
          setVertices([]);
          setHyperedges([]);
          setError(`数据库 "${dbName}" 不存在`);
          message.warning(`数据库 "${dbName}" 不存在，请选择其他数据库`);
        }
        return;
      }

      const verticesUrl = `${SERVER_URL}/db/vertices?database=${encodeURIComponent(dbName)}&page=1&page_size=1000`;
      const hyperedgesUrl = `${SERVER_URL}/db/hyperedges?database=${encodeURIComponent(dbName)}&page=1&page_size=1000`;

      console.log('[FullGraph] 请求 URL:', { verticesUrl, hyperedgesUrl });

      const [verticesRes, hyperedgesRes] = await Promise.all([
        fetch(verticesUrl),
        fetch(hyperedgesUrl)
      ]);

      console.log('[FullGraph] API 响应状态:', { vertices: verticesRes.status, hyperedges: hyperedgesRes.status });

      if (!verticesRes.ok || !hyperedgesRes.ok) {
        throw new Error('API 请求失败');
      }

      const verticesData = await verticesRes.json();
      const hyperedgesData = await hyperedgesRes.json();

      console.log('[FullGraph] API 返回数据:', { vertices: verticesData, hyperedges: hyperedgesData });

      if (isMountedRef.current) {
        const verticesList = verticesData.data || verticesData || [];
        const hyperedgesList = hyperedgesData.data || hyperedgesData || [];
        setVertices(verticesList);
        setHyperedges(hyperedgesList);
        console.log('[FullGraph] 数据已更新:', { verticesCount: verticesList.length, hyperedgesCount: hyperedgesList.length });

        if (verticesList.length === 0 && hyperedgesList.length === 0) {
          message.info(`数据库 "${dbName}" 为空，请先上传文档并嵌入`);
        } else {
          message.success(`成功加载: ${verticesList.length} 个顶点, ${hyperedgesList.length} 条超边`);
        }
      }
    } catch (err: any) {
      console.error('[FullGraph] 加载失败:', err);
      if (isMountedRef.current) {
        const errorMessage = err.message || '未知错误';
        setError(t('graph.load_failed') + ': ' + errorMessage);
        message.error(t('graph.load_failed') + ': ' + errorMessage);
        // 出错时清空数据，避免显示错误的数据
        setVertices([]);
        setHyperedges([]);
        // 出错时清空 lastLoadedDbRef，允许重试
        lastLoadedDbRef.current = null;
      }
    } finally {
      if (isMountedRef.current) {
        loadingRef.current = false;
        setLoading(false);
        console.log('[FullGraph] 加载完成，loadingRef 已重置');
      }
    }
  };

  // 监听 MobX 状态变化
  useEffect(() => {
    const dbName = storeGlobalUser.selectedDatabase || '';

    console.log('[FullGraph] useEffect 触发, dbName:', dbName, 'lastLoadedDb:', lastLoadedDbRef.current);

    if (!dbName) {
      // 数据库清空时清空数据
      console.log('[FullGraph] 数据库为空，清空数据');
      setVertices([]);
      setHyperedges([]);
      setError(null);
      lastLoadedDbRef.current = null;
      storeGlobalUser.resetVisualizationState();
    } else if (storeGlobalUser.hasUserInitiatedVisualization && lastLoadedDbRef.current !== dbName && !loadingRef.current) {
      // 只有用户手动触发可视化且数据库变化时才加载数据
      console.log('[FullGraph] 数据库变化:', lastLoadedDbRef.current, '->', dbName, '，开始加载数据');
      loadData(dbName);
    } else {
      console.log('[FullGraph] 跳过加载 - 等待用户手动触发可视化');
    }
  }, [storeGlobalUser.selectedDatabase, storeGlobalUser.hasUserInitiatedVisualization]);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      loadingRef.current = false;
    };
  }, []);

  const downloadGraphData = () => {
    const data = {
      database: storeGlobalUser.selectedDatabase,
      vertices: vertices,
      hyperedges: hyperedges,
      timestamp: new Date().toISOString()
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `hypergraph_${storeGlobalUser.selectedDatabase}_${new Date().getTime()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    message.success(t('graph.download_success'));
  };

  const handleStartVisualization = async () => {
    const dbName = storeGlobalUser.selectedDatabase;
    if (!dbName) {
      message.warning('请先选择一个数据库');
      return;
    }

    console.log('[FullGraph] 用户手动开始可视化，数据库:', dbName);

    // 验证数据库是否在可用列表中
    if (!storeGlobalUser.validateDatabaseExists(dbName)) {
      message.warning('所选数据库不存在，请重新选择');
      return;
    }

    // 设置用户已触发可视化
    storeGlobalUser.setHasUserInitiatedVisualization(true);
    storeGlobalUser.visualizationReady = true;

    // 开始加载数据
    await loadData(dbName);
  };

  const getEntityColor = (type: string) => {
    return entityTypeColors[type] || entityTypeColors.default;
  };

  const graphOptions = useMemo(() => {
    console.log('[FullGraph] 构建图数据，vertices:', vertices);
    console.log('[FullGraph] hyperedges:', hyperedges);

    // 构建节点：vertices 是字符串数组（顶点名称）
    const nodes = vertices.map((v: any, index: number) => {
      // 使用顶点名称作为节点 ID 和 label（这样能与超边数据匹配）
      const nodeName = typeof v === 'string' ? v : String(v);
      const entityType = typeof v === 'string' ? 'default' : (v.entity_type || v.type || 'default');
      const nodeColor = getNodeColorByName(nodeName);

      return {
        id: nodeName,
        label: nodeName,
        entity_type: entityType,
        color: nodeColor, // 添加颜色
        description: typeof v === 'string' ? '' : (v.description || ''),
        properties: typeof v === 'string' ? [] : ((v.additional_properties || '').split('<SEP>').filter((p: string) => p)),
        data: {
          label: nodeName,
          type: entityType,
          color: nodeColor,
          description: typeof v === 'string' ? '' : (v.description || '')
        }
      };
    }).filter((n: any) => n.id !== '');

    console.log('[FullGraph] 节点 ID 列表:', nodes.map(n => n.id).slice(0, 10));

    // 构建边（超边可视化）
    const edges: any[] = [];
    const plugins: any[] = [];

    // 创建bubble-sets样式配置（参考RetrievalHyperGraph）
    const createBubbleSetStyle = (baseColor: string) => ({
      fill: baseColor,
      stroke: baseColor,
      labelFill: '#fff',
      labelPadding: 2,
      labelBackgroundFill: baseColor,
      labelBackgroundRadius: 5,
      labelPlacement: 'center',
      labelAutoRotate: false,
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
    });

    // 添加超边bubble-sets（始终显示，展示完整超图）
    console.log('[FullGraph] 开始处理超边，数量:', hyperedges.length);
    hyperedges.forEach((he: any, index: number) => {
      const verticesList = he.vertices || [];
      console.log(`[FullGraph] 超边 ${index}:`, he);
      console.log(`[FullGraph] 超边 ${index} vertices:`, verticesList);

      // 将顶点名称转换为节点 ID
      const nodeIds = verticesList.filter((vName: string) => vName && nodes.find((n: any) => n.id === vName));
      console.log(`[FullGraph] 超边 ${index} 匹配的节点IDs:`, nodeIds);

      if (nodeIds.length > 0) {
        plugins.push({
          key: `bubble-sets-${index}`,
          type: 'bubble-sets',
          members: nodeIds,
          labelText: graphMode === 'hyperedges' ? (he.keywords || he.summary || `Hyperedge ${index + 1}`) : '',
          ...createBubbleSetStyle(bubbleSetColors[index % bubbleSetColors.length])
        });
      }
    });
    console.log('[FullGraph] 最终插件数量:', plugins.length);
    console.log('[FullGraph] 插件数组:', plugins);

    plugins.push({
      type: 'tooltip',
      getContent: (_e: any, items: any[]) => {
        let result = '';
        items.forEach((item: any) => {
          result += `<h4>${item.data?.label || item.id}</h4>`;
          if (item.entity_type) {
            result += `<p><strong>类型:</strong> ${item.entity_type}</p>`;
          }
          if (item.description) {
            const desc = item.description.split('<SEP>')[0];
            result += `<p><strong>描述:</strong> ${desc}</p>`;
          }
        });
        return result;
      },
    });

    const result = {
      autoResize: true,
      data: { nodes, edges },
      node: {
        palette: { field: 'entity_type' },
        style: {
          size: 25,
          labelText: (d: any) => d.label,
          fill: (d: any) => d.color || getEntityColor(d.entity_type),
        }
      },
      edge: {
        style: {
          size: 2,
        }
      },
      animate: false,
      layout: graphMode === 'hyperedges' ? {
        type: 'circular',
        preventOverlap: true,
        nodeSpacing: 80,
        radius: 300,
      } : {
        type: 'force-atlas2',
        preventOverlap: true,
        kr: 80,
        gravity: 20,
        linkDistance: 10,
      },
      behaviors: [
        'zoom-canvas',
        'drag-canvas',
        'drag-element',
      ],
      autoFit: { type: 'view' as const },
      plugins,
    };
    console.log('[FullGraph] 完整 Graphin options:', JSON.stringify(result, null, 2));
    return result;
  }, [vertices, hyperedges, graphMode]);

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h2 style={{ margin: 0 }}>
          <DatabaseOutlined style={{ marginRight: 8, fontSize: '24px', color: '#1890ff' }} />
          {t('graph.full_graph_title')}
        </h2>
        <DatabaseSelector
          mode="select"
          showRefresh={true}
          size="middle"
        />
      </div>

      {vertices.length > 0 || hyperedges.length > 0 ? (
        <Card style={{ marginBottom: 16 }}>
          <Spin spinning={loading}>
            <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
              <Statistic
                title={t('graph.total_vertices')}
                value={vertices.length}
                prefix={<DatabaseOutlined />}
                valueStyle={{ color: '#1890ff' }}
              />
              <Statistic
                title={t('graph.total_hyperedges')}
                value={hyperedges.length}
                prefix={<SyncOutlined />}
                valueStyle={{ color: '#52C41A' }}
              />
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={downloadGraphData}
              >
                {t('graph.download_data')}
              </Button>
            </div>
          </Spin>
        </Card>
      ) : null}

      {error && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ color: '#ff4d4f', textAlign: 'center', padding: '24px' }}>
            {error}
          </div>
        </Card>
      )}

      {!storeGlobalUser.selectedDatabase && !loading && (
        <Card style={{ textAlign: 'center', padding: '48px' }}>
          <DatabaseOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
          <p style={{ color: '#999', margin: 0 }}>{t('graph.select_database_first')}</p>
        </Card>
      )}

      {!storeGlobalUser.hasUserInitiatedVisualization ? (
        <Card style={{ textAlign: 'center', padding: '48px' }}>
          <div className="flex flex-col items-center justify-center">
            <DatabaseOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
            <h2 style={{ fontSize: 24, marginBottom: 8 }}>请选择数据库并开始可视化</h2>
            <p style={{ color: '#666', marginBottom: 24 }}>选择一个数据库后，点击下方按钮开始超图可视化</p>
            <Button
              type="primary"
              size="large"
              icon={<DatabaseOutlined />}
              onClick={handleStartVisualization}
              disabled={!storeGlobalUser.selectedDatabase}
            >
              开始可视化
            </Button>
          </div>
        </Card>
      ) : vertices.length > 0 && (
        <Card
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>{t('graph.graph_visualization')}</span>
              <Select
                value={graphMode}
                style={{ width: 150 }}
                onChange={setGraphMode}
                options={[
                  { label: '无标签', value: 'entities' },
                  { label: '显示标签', value: 'hyperedges' }
                ]}
              />
            </div>
          }
          style={{ marginBottom: 0 }}
        >
          <Spin spinning={loading}>
            <div style={{ height: 'calc(100vh - 250px)', minHeight: 600 }}>
              {graphOptions.data.nodes.length > 0 ? (
                <Graphin
                  options={graphOptions}
                  id="full-graph-viewer"
                  style={{ width: '100%', height: '100%' }}
                />
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#999' }}>
                  暂无有效节点数据
                </div>
              )}
            </div>
          </Spin>
        </Card>
      )}

      {storeGlobalUser.hasUserInitiatedVisualization && vertices.length === 0 && !error && storeGlobalUser.selectedDatabase && (
        <Card style={{ textAlign: 'center', padding: '48px' }}>
          <DatabaseOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
          <p style={{ color: '#999', margin: 0 }}>{t('graph.no_graph_data')}</p>
          <Button type="primary" onClick={() => loadData(storeGlobalUser.selectedDatabase)} style={{ marginTop: 16 }}>
            {t('graph.refresh_data')}
          </Button>
        </Card>
      )}
    </div>
  );
});

export default FullGraphPage;
