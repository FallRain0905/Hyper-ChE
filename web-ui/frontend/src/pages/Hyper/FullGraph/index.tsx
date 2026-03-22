import { useEffect, useState, useMemo } from 'react';
import { Card, Spin, Button, Statistic, message, Select } from 'antd';
import { useTranslation } from 'react-i18next';
import { storeGlobalUser } from '../../../store/globalUser';
import DatabaseSelector from '../../../components/DatabaseSelector';
import { DatabaseOutlined, DownloadOutlined, SyncOutlined } from '@ant-design/icons';
import { SERVER_URL } from '../../../utils';
import { Graphin } from '@antv/graphin';

const entityTypeColors = {
  'PERSON': '#00C9C9',
  'CONCEPT': '#a68fff',
  'ORGANIZATION': '#F08F56',
  'LOCATION': '#FFA726',
  'EVENT': '#FA8C16',
  'PRODUCT': '#722ED1',
  'default': '#8566CC'
};

const FullGraphPage = () => {
  const { t } = useTranslation();
  const [vertices, setVertices] = useState([]);
  const [hyperedges, setHyperedges] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [graphMode, setGraphMode] = useState('entities');

  // 简化加载逻辑 - 移除复杂的状态检查
  const loadFullGraph = async () => {
    const currentDb = storeGlobalUser.selectedDatabase;

    if (!currentDb) {
      return;
    }

    if (loading) {
      return;
    }

    setLoading(true);
    setError(null);
    setVertices([]);
    setHyperedges([]);

    try {
      const verticesUrl = `${SERVER_URL}/db/vertices?database=${encodeURIComponent(currentDb)}&page=1&page_size=1000`;
      const verticesRes = await fetch(verticesUrl);
      const verticesData = await verticesRes.json();
      const verticesList = verticesData.data || verticesData || [];

      const hyperedgesUrl = `${SERVER_URL}/db/hyperedges?database=${encodeURIComponent(currentDb)}&page=1&page_size=1000`;
      const hyperedgesRes = await fetch(hyperedgesUrl);
      const hyperedgesData = await hyperedgesRes.json();
      const hyperedgesList = hyperedgesData.data || hyperedgesData || [];

      setVertices(verticesList);
      setHyperedges(hyperedgesList);
      message.success(`成功加载: ${verticesList.length} 个顶点, ${hyperedgesList.length} 条超边`);
    } catch (err: any) {
      setError(t('graph.load_failed') + ': ' + err.message);
      message.error(t('graph.load_failed'));
    } finally {
      setLoading(false);
    }
  };

  // 直接响应 selectedDatabase 变化
  useEffect(() => {
    if (storeGlobalUser.selectedDatabase) {
      loadFullGraph();
    } else {
      setVertices([]);
      setHyperedges([]);
    }
  }, [storeGlobalUser.selectedDatabase]);

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

  const getEntityColor = (type: string) => {
    return entityTypeColors[type] || entityTypeColors.default;
  };

  // 使用 useMemo 优化 graphOptions
  const graphOptions = useMemo(() => {
    const hyperData = {
      nodes: vertices.map((v: any) => ({
        id: v.vertex_id,
        label: v.entity_name || v.vertex_id,
        entity_type: v.entity_type,
        description: v.description,
        properties: (v.additional_properties || '').split('<SEP>').filter((p: string) => p),
        data: {
          label: v.entity_name || v.vertex_id,
          type: v.entity_type || 'default',
          description: v.description || ''
        }
      })),
      edges: []
    };

    const plugins: any[] = [];

    if (graphMode === 'hyperedges') {
      hyperedges.forEach((he: any, index: number) => {
        const nodes = he.vertices || [];
        if (nodes.length > 0) {
          plugins.push({
            key: `bubble-sets-${index}`,
            type: 'bubble-sets',
            members: nodes,
            labelText: he.keywords || he.summary || `Hyperedge ${index + 1}`,
            ...{
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
              virtualEdges: true,
            }
          });
        }
      });
    }

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

    return {
      autoResize: true,
      data: hyperData,
      node: {
        palette: { field: 'entity_type' },
        style: {
          size: 25,
          labelText: (d: any) => d.label,
          fill: (d: any) => {
            return getEntityColor(d.entity_type);
          },
        }
      },
      edge: {
        style: {
          size: 2,
        }
      },
      animate: false,
      behaviors: [
        'zoom-canvas',
        'drag-canvas',
        'drag-element',
      ],
      autoFit: { type: 'center' as const },
      layout: {
        type: 'force',
        clustering: true,
        preventOverlap: true,
        nodeClusterBy: 'entity_type',
        gravity: 20,
        linkDistance: 150,
      },
      plugins,
    };
  }, [vertices, hyperedges, graphMode, t]);

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

      {!loading && vertices.length > 0 && (
        <Card
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>{t('graph.graph_visualization')}</span>
              <Select
                value={graphMode}
                style={{ width: 150 }}
                onChange={setGraphMode}
                options={[
                  { label: t('graph.mode_entities'), value: 'entities' },
                  { label: t('graph.mode_hyperedges'), value: 'hyperedges' }
                ]}
              />
            </div>
          }
          style={{ marginBottom: 0 }}
        >
          <div style={{ height: 'calc(100vh - 250px)', minHeight: 600 }}>
            <Graphin
              options={graphOptions}
              id="full-graph-viewer"
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </Card>
      )}

      {!loading && vertices.length === 0 && !error && storeGlobalUser.selectedDatabase && (
        <Card style={{ textAlign: 'center', padding: '48px' }}>
          <DatabaseOutlined style={{ fontSize: 64, color: '#d9d9d9', marginBottom: 16 }} />
          <p style={{ color: '#999', margin: 0 }}>{t('graph.no_graph_data')}</p>
          <Button type="primary" onClick={loadFullGraph} style={{ marginTop: 16 }}>
            {t('graph.refresh_data')}
          </Button>
        </Card>
      )}
    </div>
  );
};

export default FullGraphPage;
