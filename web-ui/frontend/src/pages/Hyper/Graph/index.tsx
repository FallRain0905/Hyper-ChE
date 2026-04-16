import React, { useEffect, useState } from 'react';
import { Select, Card, Tag, Spin, Button, message } from 'antd';
import { observer } from 'mobx-react';
import { useTranslation } from 'react-i18next';
import { storeGlobalUser } from '../../../store/globalUser';
import HyperGraph from '../../../components/HyperGraph';
import DatabaseSelector from '../../../components/DatabaseSelector';
import { DatabaseOutlined } from '@ant-design/icons';
import { SERVER_URL } from '../../../utils';

const GraphPage = () => {
  const { t } = useTranslation();
  const [keys, setKeys] = useState(undefined);
  const [key, setKey] = useState(undefined);
  const [loading, setLoading] = useState(false);
  const [item, setItem] = useState({
    entity_name: '',
    entity_type: '',
    descriptions: [''],
    properties: ['']
  });
  const [verticesList, setVerticesList] = useState([]);
  const [verticesPage, setVerticesPage] = useState(1);
  const [verticesTotal, setVerticesTotal] = useState(0);
  const [verticesLoading, setVerticesLoading] = useState(false);
  const [hypergraphType, setHypergraphType] = useState<'entity' | 'theme'>('entity');
  const [themeVerticesList, setThemeVerticesList] = useState([]);
  const [themeVerticesPage, setThemeVerticesPage] = useState(1);
  const [themeVerticesTotal, setThemeVerticesTotal] = useState(0);

  // 初始化数据库列表（但不自动恢复选择的数据库）
  useEffect(() => {
    storeGlobalUser.loadDatabases();
  }, []);

  // 获取vertices分页加载
  const loadVertices = async (page = 1, append = false) => {
    setVerticesLoading(true);
    const pageSize = 50;
    const url = `${SERVER_URL}/db/vertices?database=${encodeURIComponent(storeGlobalUser.selectedDatabase)}&page=${page}&page_size=${pageSize}`;
    const res = await fetch(url);
    const data = await res.json();
    const list = data.data || data;
    setVerticesTotal(data.total || list.length);
    setVerticesPage(page);
    setVerticesList(prev => append ? [...prev, ...list] : list);
    setVerticesLoading(false);
  };

  // 获取主题vertices分页加载
  const loadThemeVertices = async (page = 1, append = false) => {
    setVerticesLoading(true);
    const pageSize = 50;
    const url = `${SERVER_URL}/db/theme_vertices?database=${encodeURIComponent(storeGlobalUser.selectedDatabase)}&page=${page}&page_size=${pageSize}`;
    const res = await fetch(url);
    const data = await res.json();
    const list = data.data || data;
    setThemeVerticesTotal(data.total || list.length);
    setThemeVerticesPage(page);
    setThemeVerticesList(prev => append ? [...prev, ...list] : list);
    setVerticesLoading(false);
  };

  // 获取vertices列表（支持双超图）
  useEffect(() => {
    if (!storeGlobalUser.selectedDatabase || !storeGlobalUser.hasUserInitiatedVisualization) return;

    setLoading(true);

    // 根据超图类型选择不同的API端点
    const url = hypergraphType === 'theme'
      ? `${SERVER_URL}/db/theme_vertices?database=${encodeURIComponent(storeGlobalUser.selectedDatabase)}`
      : `${SERVER_URL}/db/vertices?database=${encodeURIComponent(storeGlobalUser.selectedDatabase)}`;

    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        // 处理分页数据格式
        const vertices = data.data || data;
        setKeys(vertices);
        // 设置默认选中第一个vertex
        if (vertices && vertices.length > 0) {
          setKey(vertices[0]);
        }
        setLoading(false);
      })
      .catch((error) => {
        console.error(t('graph.fetch_vertices_failed') + ':', error);
        setLoading(false);
      });
  }, [storeGlobalUser.selectedDatabase, storeGlobalUser.hasUserInitiatedVisualization, hypergraphType, t]);

  // 初始化和数据库切换时加载第一页
  useEffect(() => {
    if (storeGlobalUser.selectedDatabase && storeGlobalUser.hasUserInitiatedVisualization) {
      setVerticesList([]);
      setVerticesPage(1);
      setVerticesTotal(0);
      loadVertices(1, false);
    }
  }, [storeGlobalUser.selectedDatabase, storeGlobalUser.hasUserInitiatedVisualization]);

  // 获取选中实体的详细信息（用于右侧详情展示）
  useEffect(() => {
    if (!key || !storeGlobalUser.selectedDatabase) return;

    const url = `${SERVER_URL}/db/vertices_neighbor/${encodeURIComponent(key)}?database=${encodeURIComponent(storeGlobalUser.selectedDatabase)}`;
    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        const item = data.vertices[key];
        if (item) {
          setItem({
            entity_name: item.entity_name,
            entity_type: item.entity_type,
            descriptions: item.description ? item.description.split('<SEP>') : [''],
            properties: item.additional_properties ? item.additional_properties.split('<SEP>') : ['']
          });
        }
      })
      .catch((error) => {
        console.error(t('graph.fetch_neighbor_data_failed') + ':', error);
      });
  }, [key, storeGlobalUser.selectedDatabase, t]);

  // 数据库切换处理
  const onDatabaseChange = () => {
    // 清空选择
    setKey(undefined);
    setItem({
      entity_name: '',
      entity_type: '',
      descriptions: [''],
      properties: ['']
    });
  };

  // 当数据库不存在时重置状态
  useEffect(() => {
    const dbName = storeGlobalUser.selectedDatabase;

    if (storeGlobalUser.hasUserInitiatedVisualization && dbName) {
      // 验证数据库是否还在可用列表中
      if (!storeGlobalUser.validateDatabaseExists(dbName)) {
        console.log('[Graph] 数据库已被删除，重置状态');
        storeGlobalUser.resetVisualizationState();
        setKeys(undefined);
        setKey(undefined);
        setVerticesList([]);
        setVerticesPage(1);
        setVerticesTotal(0);
        message.warning(`数据库 "${dbName}" 已被删除`);
      }
    }
  }, [storeGlobalUser.selectedDatabase, storeGlobalUser.availableDatabases, storeGlobalUser.hasUserInitiatedVisualization]);

  const handleStartVisualization = async () => {
    const dbName = storeGlobalUser.selectedDatabase;
    if (!dbName) {
      message.warning('请先选择一个数据库');
      return;
    }

    console.log('[Graph] 用户手动开始可视化，数据库:', dbName);

    // 验证数据库是否在可用列表中
    if (!storeGlobalUser.validateDatabaseExists(dbName)) {
      message.warning('所选数据库不存在，请重新选择');
      return;
    }

    // 设置用户已触发可视化
    storeGlobalUser.setHasUserInitiatedVisualization(true);
    storeGlobalUser.visualizationReady = true;

    // 开始加载数据
    setLoading(true);
    const url = `${SERVER_URL}/db/vertices?database=${encodeURIComponent(dbName)}`;
    try {
      const response = await fetch(url);
      const data = await response.json();
      // 处理分页数据格式
      const vertices = data.data || data;
      setKeys(vertices);
      // 设置默认选中第一个vertex
      if (vertices && vertices.length > 0) {
        setKey(vertices[0]);
      }
      // 同时加载第一页数据
      setVerticesList([]);
      setVerticesPage(1);
      setVerticesTotal(0);
      loadVertices(1, false);
      setLoading(false);
    } catch (error) {
      console.error('加载数据失败:', error);
      message.error('加载数据失败，请重试');
      setLoading(false);
    }
  };

  // 渲染加载状态
  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '400px',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <Spin size="large" />
        <div>{t('graph.loading_data')}</div>
      </div>
    );
  }

  // 渲染未选择数据库状态
  if (!storeGlobalUser.selectedDatabase) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '400px',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <DatabaseOutlined style={{ fontSize: '48px', color: '#d9d9d9' }} />
        <div>{t('graph.select_database_first')}</div>
        <DatabaseSelector
          mode="select"
          showRefresh={true}
          size="middle"
          onChange={onDatabaseChange}
        />
      </div>
    );
  }

  // 渲染未开始可视化状态
  if (!storeGlobalUser.hasUserInitiatedVisualization) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '400px',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <DatabaseOutlined style={{ fontSize: '64px', color: '#d9d9d9' }} />
        <h2 style={{ fontSize: 24, margin: 0 }}>请选择数据库并开始可视化</h2>
        <p style={{ color: '#666', margin: 0 }}>选择一个数据库后，点击下方按钮开始超图关系可视化</p>
        <Button
          type="primary"
          size="large"
          icon={<DatabaseOutlined />}
          onClick={handleStartVisualization}
        >
          开始可视化
        </Button>
      </div>
    );
  }

  // 渲染无数据状态（只有在用户已开始可视化时）
  if (storeGlobalUser.hasUserInitiatedVisualization && (!keys || keys.length === 0)) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '400px',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <DatabaseOutlined style={{ fontSize: '48px', color: '#d9d9d9' }} />
        <div>{t('graph.no_entity_data')}</div>
        <div style={{ color: '#999' }}>{t('graph.database_label')}: {storeGlobalUser.selectedDatabase}</div>
        <DatabaseSelector
          mode="select"
          showRefresh={true}
          size="middle"
          onChange={onDatabaseChange}
        />
      </div>
    );
  }

  return (
    <>
      <div className='m-4' style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 5 }}>
        <span>{t('graph.hypergraph_database')}</span>
        <DatabaseSelector
          mode="compact"
          showRefresh={false}
          size="middle"
          onChange={onDatabaseChange}
        />

        <span className='ml-4'>超图类型</span>
        <Select
          value={hypergraphType}
          onChange={(value) => {
            setHypergraphType(value);
            // 切换超图类型时重置选择
            setKey(undefined);
            setItem({
              entity_name: '',
              entity_type: '',
              descriptions: [''],
              properties: ['']
            });
          }}
          style={{ width: 120 }}
          size="middle"
        >
          <Select.Option value="entity">实体超图</Select.Option>
          <Select.Option value="theme">主题超图</Select.Option>
        </Select>

        <span className='ml-4'>{t('graph.select_entity')}</span>
        <Select
          value={key}
          style={{ width: 300 }}
          showSearch
          loading={verticesLoading}
          placeholder={t('graph.select_entity_placeholder')}
          onChange={setKey}
          onPopupScroll={e => {
            const target = e.target;
            if (target.scrollTop + target.offsetHeight >= target.scrollHeight - 10) {
              if (verticesList.length < verticesTotal && !verticesLoading) {
                loadVertices(verticesPage + 1, true);
              }
            }
          }}
        >
          {verticesList.map(vertexKey => (
            <Select.Option key={vertexKey} value={vertexKey}>
              {vertexKey}
            </Select.Option>
          ))}
        </Select>
      </div>

      <div style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between' }}>
        {/* 使用HyperGraph组件展示超图 */}
        <div style={{ width: '70%' }}>
          <HyperGraph
            vertexId={key}
            database={storeGlobalUser.selectedDatabase}
            height="calc(100vh - 100px)"
            width="100%"
            showTooltip={true}
            graphId="graph-page-hypergraph"
            hypergraphType={hypergraphType}
          />
        </div>

        {/* 实体详情卡片 */}
        <Card 
          title={t('graph.entity_details')}
          style={{ width: '28%', height: '600px', overflow: 'auto' }}
        >
          <p><strong>{t('graph.entity_name')}:</strong> {item.entity_name}</p>
          <p><strong>{t('graph.entity_type')}:</strong> <Tag color="blue">{item.entity_type}</Tag></p>
          <p><strong>{t('graph.description')}:</strong></p>
          <ul>
            {item.descriptions.map((desc, idx) => (
              <li key={idx}>{desc}</li>
            ))}
          </ul>
          <p><strong>{t('graph.properties')}:</strong></p>
          <ul>
            {item.properties.map((prop, idx) => (
              <li key={idx}>{prop}</li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
};

export default observer(GraphPage);