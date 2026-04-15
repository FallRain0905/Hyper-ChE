import React, { useState, useEffect } from 'react'
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  message,
  Space,
  Divider,
  Typography,
  Alert,
  Row,
  Col,
  AutoComplete,
  Checkbox
} from 'antd'
import {
  SettingOutlined,
  KeyOutlined,
  DatabaseOutlined,
  ApiOutlined,
  SaveOutlined,
  ReloadOutlined,
  GlobalOutlined,
  AppstoreOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import LanguageSelector from '../../components/LanguageSelector'
import { SERVER_URL } from '../../utils'

const { Title, Text } = Typography
const { Option } = Select
const { Password } = Input

const Setting: React.FC = () => {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [availableDatabases, setAvailableDatabases] = useState<any[]>([])
  const [testResults, setTestResults] = useState<any>({})
  const [isCustomEmbedding, setIsCustomEmbedding] = useState(false)
  const [useCustomEmbeddingApi, setUseCustomEmbeddingApi] = useState(false)

  // 默认配置
  const defaultSettings = {
    apiKey: '',
    modelProvider: 'openai',
    modelName: 'gpt-3.5-turbo',
    baseUrl: 'https://api.openai.com/v1',
    selectedDatabase: '',
    maxTokens: 2000,
    temperature: 0.7,
    // 嵌入模型配置
    embeddingModel: 'text-embedding-3-small',
    embeddingDim: 1536,
    embeddingProvider: 'same', // 'same' 使用与聊天模型相同的API配置, 'custom' 使用独立配置
    embeddingBaseUrl: '',
    embeddingApiKey: '',
    // 新增Mode配置，默认显示所有modes（包含Cog-RAG）
    availableModes: ['llm', 'naive', 'graph', 'hyper', 'hyper-lite', 'cog', 'cog-hybrid', 'cog-entity', 'cog-theme']
  }

  // 可用的查询模式配置
  const queryModes = [
    // HyperRAG 模式
    { value: 'llm', label: 'LLM', icon: '🤖', description: '仅使用大语言模型直接回答', system: 'hyperrag' },
    { value: 'naive', label: 'RAG', icon: '📚', description: '基础检索增强生成', system: 'hyperrag' },
    { value: 'graph', label: 'Graph-RAG', icon: '🕸️', description: '基于图结构的检索增强生成', system: 'hyperrag' },
    { value: 'hyper', label: 'Hyper-RAG', icon: '⚡', description: '基于超图的检索增强生成', system: 'hyperrag' },
    {
      value: 'hyper-lite',
      label: 'Hyper-RAG-Lite',
      icon: '🔸',
      description: '轻量级超图检索增强生成',
      system: 'hyperrag'
    },
    // Cog-RAG 模式
    { value: 'cog', label: 'Cog-RAG', icon: '🧠', description: '双超图认知检索（实体+主题）', system: 'cograg' },
    { value: 'cog-hybrid', label: 'Cog-Hybrid', icon: '🔄', description: '混合模式：结合实体和主题检索', system: 'cograg' },
    { value: 'cog-entity', label: 'Cog-Entity', icon: '🔷', description: '仅使用实体超图检索', system: 'cograg' },
    { value: 'cog-theme', label: 'Cog-Theme', icon: '🎨', description: '仅使用主题超图检索', system: 'cograg' }
  ]

  // 模型提供商配置
  const modelProviders = [
    {
      value: 'openai',
      label: 'OpenAI',
      models: ['gpt-5', 'gpt-5-mini', 'gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'],
      defaultBaseUrl: 'https://api.openai.com/v1'
    },
    {
      value: 'azure',
      label: 'Azure OpenAI',
      models: ['gpt-5', 'gpt-5-mini', 'gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'],
      defaultBaseUrl: 'https://your-resource.openai.azure.com'
    },
    {
      value: 'anthropic',
      label: 'Anthropic',
      models: ['claude-4-haiku', 'claude-4-sonnet', 'claude-4-opus'],
      defaultBaseUrl: 'https://api.anthropic.com'
    },
    {
      value: 'custom',
      label: t('settings.custom_api') || '自定义API',
      models: ['custom-model'],
      defaultBaseUrl: 'http://localhost:11434'
    }
  ]

  // 嵌入模型配置
  const embeddingModels = [
    // OpenAI 模型
    {
      value: 'text-embedding-3-small',
      label: 'OpenAI text-embedding-3-small',
      dim: 1536,
      description: 'OpenAI 最新小型嵌入模型，1536维，性价比高',
      provider: 'openai'
    },
    {
      value: 'text-embedding-3-large',
      label: 'OpenAI text-embedding-3-large',
      dim: 3072,
      description: 'OpenAI 最新大型嵌入模型，3072维，精度更高',
      provider: 'openai'
    },
    {
      value: 'text-embedding-ada-002',
      label: 'OpenAI text-embedding-ada-002',
      dim: 1536,
      description: 'OpenAI 经典嵌入模型，1536维',
      provider: 'openai'
    },
    // 阿里云百炼模型
    {
      value: 'text-embedding-v3',
      label: '阿里云百炼 text-embedding-v3',
      dim: 1536,
      description: '阿里云百炼最新嵌入模型，1536维，中文效果最佳 (CMTEB: 68.92)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'text-embedding-v2',
      label: '阿里云百炼 text-embedding-v2',
      dim: 1536,
      description: '阿里云百炼嵌入模型，1536维，中文效果好 (CMTEB: 62.17)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'text-embedding-v1',
      label: '阿里云百炼 text-embedding-v1',
      dim: 1536,
      description: '阿里云百炼基础嵌入模型，1536维 (CMTEB: 59.84)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    // Qwen3-Embedding 模型 (最新SOTA)
    {
      value: 'qwen3-embedding-8b',
      label: 'Qwen3-Embedding-8B',
      dim: 4096,
      description: 'Qwen3最新8B嵌入模型，4096维，MTEB多语言第一 (70.58分)，支持100+语言',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'qwen3-embedding-4b',
      label: 'Qwen3-Embedding-4B',
      dim: 2560,
      description: 'Qwen3最新4B嵌入模型，2560维，性能优异 (MTEB: 69.45分)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'qwen3-embedding-0.6b',
      label: 'Qwen3-Embedding-0.6B',
      dim: 1024,
      description: 'Qwen3最新0.6B轻量级嵌入模型，1024维，高效实用 (MTEB: 64.33分)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    // 其他开源模型
    {
      value: 'bge-large-zh-v1.5',
      label: 'BGE-large-zh-v1.5',
      dim: 1024,
      description: '智源AI中文嵌入模型，1024维，中文效果好',
      provider: 'custom'
    },
    {
      value: 'm3e-base',
      label: 'M3E-base',
      dim: 768,
      description: '开源多语言嵌入模型，768维',
      provider: 'custom'
    },
    {
      value: 'text2vec-large-chinese',
      label: 'text2vec-large-chinese',
      dim: 1024,
      description: '中文语义理解模型，1024维',
      provider: 'custom'
    },
    {
      value: 'paraphrase-multilingual-mpnet-base-v2',
      label: 'paraphrase-multilingual-mpnet-base-v2',
      dim: 768,
      description: '多语言语义模型，768维',
      provider: 'custom'
    },
    // 自定义选项
    {
      value: 'custom-4096',
      label: '自定义 4096维模型',
      dim: 4096,
      description: '自定义嵌入模型，4096维',
      provider: 'custom'
    },
    {
      value: 'custom-2048',
      label: '自定义 2048维模型',
      dim: 2048,
      description: '自定义嵌入模型，2048维',
      provider: 'custom'
    },
    {
      value: 'custom-1024',
      label: '自定义 1024维模型',
      dim: 1024,
      description: '自定义嵌入模型，1024维',
      provider: 'custom'
    },
    {
      value: 'custom-768',
      label: '自定义 768维模型',
      dim: 768,
      description: '自定义嵌入模型，768维',
      provider: 'custom'
    },
    {
      value: 'custom',
      label: '完全自定义',
      dim: 0,
      description: '自定义模型名称和维度',
      provider: 'custom'
    }
  ]

  // 加载设置
  const loadSettings = async () => {
    setLoading(true)
    try {
      // 首先尝试从localStorage加载Mode配置
      const localModeSettings = localStorage.getItem('hyperrag_mode_settings')
      console.log('📥 [Settings] 从localStorage加载Mode设置:', localModeSettings) // 调试日志

      let modeSettings = {}
      if (localModeSettings) {
        try {
          modeSettings = JSON.parse(localModeSettings)
          console.log('📊 [Settings] 解析后的Mode设置:', modeSettings) // 调试日志
        } catch (e) {
          console.error('解析本地Mode设置失败:', e)
        }
      }

      const response = await fetch(`${SERVER_URL}/settings`)
      if (response.ok) {
        const settings = await response.json()

        // 处理自定义嵌入模型
        let embeddingModel = settings.embeddingModel || defaultSettings.embeddingModel
        let customEmbeddingModel = ''

        // 检查是否为自定义模型（不在预定义列表中）
        const isCustomModel = !embeddingModels.find(m => m.value === embeddingModel)
        if (isCustomModel) {
          customEmbeddingModel = embeddingModel
          embeddingModel = 'custom'
          setIsCustomEmbedding(true)
        } else {
          setIsCustomEmbedding(false)
        }

        const finalSettings = {
          ...defaultSettings,
          ...settings,
          ...modeSettings,
          embeddingModel,
          customEmbeddingModel
        }
        console.log('🎯 [Settings] 最终设置的表单值:', finalSettings) // 调试日志

        // 设置嵌入服务提供商状态
        setUseCustomEmbeddingApi(settings.embeddingProvider === 'custom')

        form.setFieldsValue(finalSettings)
      } else {
        // 如果获取失败，使用默认设置加上本地Mode设置
        const finalSettings = { ...defaultSettings, ...modeSettings }
        console.log('🎯 [Settings] 最终设置的表单值 (API失败):', finalSettings) // 调试日志
        form.setFieldsValue(finalSettings)
      }
    } catch (error) {
      console.error('加载设置失败:', error)
      // 尝试加载本地Mode设置
      const localModeSettings = localStorage.getItem('hyperrag_mode_settings')
      console.log('📥 [Settings] 从localStorage加载Mode设置 (异常):', localModeSettings) // 调试日志

      let modeSettings = {}
      if (localModeSettings) {
        try {
          modeSettings = JSON.parse(localModeSettings)
          console.log('📊 [Settings] 解析后的Mode设置 (异常):', modeSettings) // 调试日志
        } catch (e) {
          console.error('解析本地Mode设置失败:', e)
        }
      }
      const finalSettings = { ...defaultSettings, ...modeSettings }
      console.log('🎯 [Settings] 最终设置的表单值 (异常):', finalSettings) // 调试日志
      form.setFieldsValue(finalSettings)
      setIsCustomEmbedding(false) // 重置自定义状态
      message.warning(t('settings.load_failed'))
    } finally {
      setLoading(false)
    }
  }

  // 加载可用数据库列表
  const loadDatabases = async () => {
    try {
      const response = await fetch(`${SERVER_URL}/databases`)
      if (response.ok) {
        const databases = await response.json()
        setAvailableDatabases(databases)
      }
    } catch (error) {
      console.error('加载数据库列表失败:', error)
      // 如果API不存在，提供一些默认选项
      setAvailableDatabases([
        { name: 'hypergraph_wukong', description: '西游记超图' },
        { name: 'hypergraph_A_Christmas_Carol', description: '圣诞颂歌超图' }
      ])
    }
  }

  // 保存设置
  const saveSettings = async (values: any) => {
    setSaveLoading(true)
    try {
      // 分离Mode设置和其他设置
      const { availableModes, customEmbeddingModel, ...otherSettings } = values

      console.log('💾 保存设置 - availableModes:', availableModes) // 调试日志
      console.log('💾 保存设置 - availableModes 类型:', typeof availableModes) // 调试日志
      console.log('💾 保存设置 - otherSettings:', otherSettings) // 调试日志

      // 处理自定义嵌入模型
      let finalEmbeddingModel = otherSettings.embeddingModel
      if (otherSettings.embeddingModel === 'custom' && customEmbeddingModel) {
        finalEmbeddingModel = customEmbeddingModel
        console.log('💾 使用自定义嵌入模型:', finalEmbeddingModel)
      }

      const settingsToSave = {
        ...otherSettings,
        embeddingModel: finalEmbeddingModel
      }

      // 确保 availableModes 始终是数组
      const normalizedModes = Array.isArray(availableModes) ? availableModes : [availableModes]
      console.log('💾 保存设置 - normalizedModes:', normalizedModes) // 调试日志

      // Mode设置保存到localStorage
      const modeSettings = { availableModes: normalizedModes }
      localStorage.setItem('hyperrag_mode_settings', JSON.stringify(modeSettings))
      console.log('✅ 已保存到localStorage hyperrag_mode_settings') // 调试日志

      const response = await fetch(`${SERVER_URL}/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(settingsToSave)
      })

      if (response.ok) {
        message.success(t('settings.save_success'))
        // 保存到本地存储作为备份
        localStorage.setItem('hyperrag_settings', JSON.stringify(settingsToSave))
      } else {
        throw new Error(t('settings.save_failed'))
      }
    } catch (error) {
      console.error('保存设置失败:', error)
      // 即使后端保存失败，也保存到本地存储
      const { availableModes, customEmbeddingModel, ...otherSettings } = values
      // 处理自定义嵌入模型
      let finalEmbeddingModel = otherSettings.embeddingModel
      if (otherSettings.embeddingModel === 'custom' && customEmbeddingModel) {
        finalEmbeddingModel = customEmbeddingModel
      }
      const settingsToSave = {
        ...otherSettings,
        embeddingModel: finalEmbeddingModel
      }
      // 确保 availableModes 始终是数组
      const normalizedModes = Array.isArray(availableModes) ? availableModes : [availableModes]
      localStorage.setItem('hyperrag_settings', JSON.stringify(settingsToSave))
      localStorage.setItem('hyperrag_mode_settings', JSON.stringify({ availableModes: normalizedModes }))
      message.warning(t('settings.backend_save_failed'))
    } finally {
      setSaveLoading(false)
    }
  }

  // 测试API连接
  const testAPIConnection = async () => {
    const values = form.getFieldsValue()
    if (!values.apiKey) {
      message.error(t('settings.api_key_required'))
      return
    }

    setTestResults({ ...testResults, api: 'testing' })
    try {
      const response = await fetch(`${SERVER_URL}/test-api`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          apiKey: values.apiKey,
          baseUrl: values.baseUrl,
          modelName: values.modelName,
          modelProvider: values.modelProvider
        })
      })

      if (response.ok) {
        const result = await response.json()
        setTestResults({ ...testResults, api: 'success' })
        message.success(t('settings.api_test_success'))
      } else {
        setTestResults({ ...testResults, api: 'failed' })
        message.error(t('settings.api_test_failed'))
      }
    } catch (error: any) {
      setTestResults({ ...testResults, api: 'failed' })
      message.error(t('settings.api_test_failed') + ': ' + error.message)
    }
  }

  // 测试数据库连接
  const testDatabaseConnection = async () => {
    const values = form.getFieldsValue()
    if (!values.selectedDatabase) {
      message.error(t('settings.database_required'))
      return
    }

    setTestResults({ ...testResults, database: 'testing' })
    try {
      const response = await fetch(`${SERVER_URL}/test-database`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          database: values.selectedDatabase
        })
      })

      if (response.ok) {
        setTestResults({ ...testResults, database: 'success' })
        message.success(t('settings.database_test_success'))
      } else {
        setTestResults({ ...testResults, database: 'failed' })
        message.error(t('settings.database_test_failed'))
      }
    } catch (error: any) {
      setTestResults({ ...testResults, database: 'failed' })
      message.error(t('settings.database_test_failed') + ': ' + error.message)
    }
  }

  // 重置设置
  const resetSettings = () => {
    form.setFieldsValue(defaultSettings)
    setTestResults({})
    // 也清除localStorage中的Mode设置
    localStorage.removeItem('hyperrag_mode_settings')
    message.info(t('settings.reset_success'))
  }

  // 监听模型提供商变化
  const handleProviderChange = (value: string) => {
    const provider = modelProviders.find(p => p.value === value)
    if (provider) {
      form.setFieldsValue({
        baseUrl: provider.defaultBaseUrl,
        modelName: provider.models[0] // 设置默认模型，用户仍可输入自定义模型
      })
    }
  }

  // 处理嵌入模型变化
  const handleEmbeddingModelChange = (value: string) => {
    const model = embeddingModels.find(m => m.value === value)
    if (model) {
      // 检查是否为完全自定义
      const isCustom = value === 'custom'
      setIsCustomEmbedding(isCustom)

      if (!isCustom) {
        form.setFieldsValue({
          embeddingDim: model.dim // 自动设置对应的维度
        })

        // 如果是阿里云百炼模型，自动设置base_url并提示使用独立API配置
        if (model.provider === 'bailian' && model.baseUrl) {
          setUseCustomEmbeddingApi(true)
          form.setFieldsValue({
            embeddingProvider: 'custom',
            embeddingBaseUrl: model.baseUrl
          })
          message.info(`已自动设置阿里云百炼API地址，请配置您的阿里云百炼API Key`)
        }
        // 如果是OpenAI模型，恢复使用相同API配置
        else if (model.provider === 'openai') {
          setUseCustomEmbeddingApi(false)
          form.setFieldsValue({
            embeddingProvider: 'same',
            embeddingBaseUrl: '',
            embeddingApiKey: ''
          })
        }
      }
    }
  }

  // 处理嵌入服务提供商变化
  const handleEmbeddingProviderChange = (value: string) => {
    const useCustom = value === 'custom'
    setUseCustomEmbeddingApi(useCustom)

    if (!useCustom) {
      // 如果选择使用相同的API配置，清空自定义配置
      form.setFieldsValue({
        embeddingBaseUrl: '',
        embeddingApiKey: ''
      })
    }
  }

  useEffect(() => {
    loadSettings()
    loadDatabases()
  }, [])

  return (
    <div className="m-2">
      <Card>
        <div className="mb-4">
          <div className="flex items-center text-2xl font-bold">
            <SettingOutlined style={{ marginRight: '8px' }} />
            {t('settings.title')}
          </div>
          <Text type="secondary">{t('settings.subtitle')}</Text>
        </div>

        <Form form={form} layout="vertical" onFinish={saveSettings} initialValues={defaultSettings}>
          {/* 添加调试信息 */}
          {console.log('📋 Settings表单初始值:', defaultSettings)}
          {/* 系统配置区块 */}
          <Card
            title={
              <span>
                <GlobalOutlined style={{ marginRight: '8px' }} />
                {t('settings.system_config')}
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Form.Item label={t('settings.language_select')}>
              <LanguageSelector />
            </Form.Item>
          </Card>

          {/* API 配置区块 */}
          <Card
            title={
              <span>
                <ApiOutlined style={{ marginRight: '8px' }} />
                {t('settings.api_config')}
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Alert
              message={t('settings.api_config')}
              description={t('settings.api_description')}
              type="info"
              showIcon
              style={{ marginBottom: '24px' }}
            />

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="modelProvider"
                  label={t('settings.model_provider')}
                  rules={[{ required: true, message: t('settings.provider_required') }]}
                >
                  <Select onChange={handleProviderChange}>
                    {modelProviders.map(provider => (
                      <Option key={provider.value} value={provider.value}>
                        {provider.label}
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="modelName"
                  label={t('settings.model_name')}
                  rules={[{ required: true, message: t('settings.model_required') }]}
                  extra={t('settings.model_name_help')}
                >
                  <AutoComplete
                    placeholder={t('settings.model_name_placeholder')}
                    allowClear
                    filterOption={(inputValue, option) =>
                      option!.value.toLowerCase().includes(inputValue.toLowerCase())
                    }
                    options={
                      form.getFieldValue('modelProvider')
                        ? modelProviders
                            .find(p => p.value === form.getFieldValue('modelProvider'))
                            ?.models.map(model => ({
                              value: model,
                              label: model
                            })) || []
                        : []
                    }
                  />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item
              name="baseUrl"
              label={t('settings.api_base_url')}
              rules={[{ required: true, message: t('settings.base_url_required') }]}
            >
              <Input placeholder="https://api.openai.com/v1" />
            </Form.Item>

            <Form.Item
              name="apiKey"
              label={t('settings.api_key')}
              rules={[{ required: true, message: t('settings.api_key_required') }]}
            >
              <Password
                placeholder={t('settings.api_key_placeholder')}
                iconRender={visible => (visible ? <KeyOutlined /> : <KeyOutlined />)}
              />
            </Form.Item>

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="maxTokens"
                  label={t('settings.max_tokens')}
                  rules={[{ required: true, message: t('settings.max_tokens_required') }]}
                >
                  <Input type="number" min={1} max={8000} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="temperature"
                  label={t('settings.temperature')}
                  rules={[{ required: true, message: t('settings.temperature_required') }]}
                >
                  <Input type="number" min={0} max={2} step={0.1} />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item>
              <Button
                type="default"
                onClick={testAPIConnection}
                loading={testResults.api === 'testing'}
                style={{ marginRight: '8px' }}
              >
                {t('settings.test_api_connection')}
              </Button>
              {testResults.api === 'success' && (
                <Text type="success">{t('settings.connection_success')}</Text>
              )}
              {testResults.api === 'failed' && (
                <Text type="danger">{t('settings.connection_failed')}</Text>
              )}
            </Form.Item>
          </Card>

          {/* 嵌入模型配置区块 */}
          <Card
            title={
              <span>
                <DatabaseOutlined style={{ marginRight: '8px' }} />
                嵌入模型配置
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Alert
              message="嵌入模型配置"
              description="选择用于文档向量化的嵌入模型。不同模型有不同的维度和性能特征。更换模型需要清空现有数据库。"
              type="warning"
              showIcon
              style={{ marginBottom: '24px' }}
            />

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="embeddingModel"
                  label="嵌入模型"
                  rules={[{ required: true, message: '请选择嵌入模型' }]}
                >
                  <Select
                    onChange={handleEmbeddingModelChange}
                    placeholder="选择嵌入模型"
                  >
                    {embeddingModels.map(model => (
                      <Option key={model.value} value={model.value}>
                        <div>
                          <div style={{ fontWeight: 'bold' }}>{model.label}</div>
                          <div style={{ fontSize: '12px', color: '#666' }}>
                            {model.dim} 维 - {model.description}
                          </div>
                        </div>
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="embeddingDim"
                  label="嵌入维度"
                  rules={[{ required: true, message: '请输入嵌入维度' }]}
                  extra="向量维度，由嵌入模型决定"
                >
                  <Input
                    type="number"
                    disabled={!isCustomEmbedding}
                    placeholder={isCustomEmbedding ? "请输入维度" : "自动根据模型设置"}
                  />
                </Form.Item>
              </Col>
            </Row>

            {/* 自定义模型名称输入 */}
            {isCustomEmbedding && (
              <Row gutter={16}>
                <Col span={24}>
                  <Form.Item
                    name="customEmbeddingModel"
                    label="自定义模型名称"
                    rules={[{ required: true, message: '请输入自定义模型名称' }]}
                    extra="请输入你要使用的嵌入模型名称，例如：your-custom-model"
                  >
                    <Input placeholder="例如：your-custom-model" />
                  </Form.Item>
                </Col>
              </Row>
            )}

            {/* 嵌入服务提供商配置 */}
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item
                  name="embeddingProvider"
                  label="嵌入API配置"
                  rules={[{ required: true, message: '请选择嵌入API配置' }]}
                  extra="选择嵌入模型使用的API配置"
                >
                  <Select onChange={handleEmbeddingProviderChange}>
                    <Option value="same">
                      <div>
                        <div style={{ fontWeight: 'bold' }}>使用与聊天模型相同的API配置</div>
                        <div style={{ fontSize: '12px', color: '#666' }}>
                          嵌入模型将使用上方配置的API Key和Base URL
                        </div>
                      </div>
                    </Option>
                    <Option value="custom">
                      <div>
                        <div style={{ fontWeight: 'bold' }}>使用独立的嵌入API配置</div>
                        <div style={{ fontSize: '12px', color: '#666' }}>
                          为嵌入模型配置独立的API Key和Base URL
                        </div>
                      </div>
                    </Option>
                  </Select>
                </Form.Item>
              </Col>
            </Row>

            {/* 自定义嵌入API配置 */}
            {useCustomEmbeddingApi && (
              <>
                <Alert
                  message="嵌入API配置说明"
                  description={
                    <div>
                      <p><strong>阿里云百炼配置：</strong></p>
                      <ul style={{ marginLeft: '20px', marginTop: '8px' }}>
                        <li>Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1</li>
                        <li>API Key: 从阿里云百炼控制台获取的API-KEY</li>
                        <li>官方文档: <a href="https://help.aliyun.com/zh/model-studio/dashscopeembedding-in-llamaindex" target="_blank" rel="noopener noreferrer">查看文档</a></li>
                      </ul>
                      <p style={{ marginTop: '8px' }}><strong>其他自定义API：</strong></p>
                      <p style={{ marginLeft: '20px', marginTop: '4px' }}>请根据您的API提供商填写相应的Base URL和API Key</p>
                    </div>
                  }
                  type="info"
                  showIcon
                  style={{ marginBottom: '16px' }}
                />
                <Row gutter={16}>
                  <Col span={24}>
                    <Form.Item
                      name="embeddingBaseUrl"
                      label="嵌入API Base URL"
                      rules={[{ required: true, message: '请输入嵌入API的Base URL' }]}
                      extra="嵌入模型的API端点，例如：https://dashscope.aliyuncs.com/compatible-mode/v1"
                    >
                      <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={16}>
                  <Col span={24}>
                    <Form.Item
                      name="embeddingApiKey"
                      label="嵌入API Key"
                      rules={[{ required: true, message: '请输入嵌入API的Key' }]}
                      extra="嵌入模型的API密钥，例如：sk-xxxxxxxxxxxxxxxx"
                    >
                      <Password
                        placeholder="请输入嵌入API的密钥"
                        iconRender={visible => (visible ? <KeyOutlined /> : <KeyOutlined />)}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </>
            )}

            <Alert
              message="重要提示"
              description="更换嵌入模型后，需要清空现有数据库重新嵌入文档，否则会因维度不匹配导致错误。"
              type="error"
              showIcon
              style={{ marginTop: '16px' }}
            />
          </Card>

          {/* Mode配置区块 */}
          <Card
            title={
              <span>
                <AppstoreOutlined style={{ marginRight: '8px' }} />
                查询模式配置
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Alert
              message="查询模式配置"
              description="选择在聊天界面中显示的查询模式。配置将保存在本地浏览器中。"
              type="info"
              showIcon
              style={{ marginBottom: '24px' }}
            />

            <Form.Item
              name="availableModes"
              label="可用的查询模式"
              extra="选择在聊天界面侧边栏中显示的查询模式"
            >
              <Checkbox.Group style={{ width: '100%' }}>
                {/* HyperRAG 系统分组 */}
                <div style={{ marginBottom: '24px' }}>
                  <div style={{
                    fontSize: '14px',
                    fontWeight: 'bold',
                    color: '#1890ff',
                    marginBottom: '12px',
                    padding: '8px 12px',
                    background: '#f0f5ff',
                    borderRadius: '4px',
                    borderLeft: '3px solid #1890ff'
                  }}>
                    HyperRAG 系统
                  </div>
                  <Row gutter={[16, 16]}>
                    {queryModes.filter(m => m.system === 'hyperrag').map(mode => (
                      <Col span={12} key={mode.value}>
                        <Card size="small" style={{ height: '100%' }}>
                          <Checkbox value={mode.value} style={{ width: '100%' }}>
                            <div style={{ marginLeft: '8px' }}>
                              <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
                                <span style={{ marginRight: '6px' }}>{mode.icon}</span>
                                {mode.label}
                              </div>
                              <div style={{ fontSize: '12px', color: '#666', marginTop: '4px' }}>
                                {mode.description}
                              </div>
                            </div>
                          </Checkbox>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                </div>

                {/* Cog-RAG 系统分组 */}
                <div>
                  <div style={{
                    fontSize: '14px',
                    fontWeight: 'bold',
                    color: '#722ed1',
                    marginBottom: '12px',
                    padding: '8px 12px',
                    background: '#f9f0ff',
                    borderRadius: '4px',
                    borderLeft: '3px solid #722ed1'
                  }}>
                    Cog-RAG 系统
                  </div>
                  <Row gutter={[16, 16]}>
                    {queryModes.filter(m => m.system === 'cograg').map(mode => (
                      <Col span={12} key={mode.value}>
                        <Card size="small" style={{ height: '100%' }}>
                          <Checkbox value={mode.value} style={{ width: '100%' }}>
                            <div style={{ marginLeft: '8px' }}>
                              <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
                                <span style={{ marginRight: '6px' }}>{mode.icon}</span>
                                {mode.label}
                              </div>
                              <div style={{ fontSize: '12px', color: '#666', marginTop: '4px' }}>
                                {mode.description}
                              </div>
                            </div>
                          </Checkbox>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                </div>
              </Checkbox.Group>
            </Form.Item>
          </Card>

          {/* 数据库配置区块 */}
          {/* <Card
            title={
              <span>
                <DatabaseOutlined style={{ marginRight: '8px' }} />
                {t('settings.database_config')}
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Alert
              message={t('settings.database_config')}
              description={t('settings.database_description')}
              type="info"
              showIcon
              style={{ marginBottom: '24px' }}
            />

            <Form.Item
              name="selectedDatabase"
              label={t('settings.select_database')}
              rules={[{ required: true, message: t('settings.database_selection_required') }]}
            >
              <Select placeholder={t('settings.select_database_placeholder')} loading={loading}>
                {availableDatabases.map(db => (
                  <Option key={db.name} value={db.name}>
                    <div>
                      <div style={{ fontWeight: 'bold' }}>{db.name}</div>
                      {db.description && (
                        <div style={{ fontSize: '12px', color: '#666' }}>{db.description}</div>
                      )}
                    </div>
                  </Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item>
              <Button
                type="default"
                onClick={testDatabaseConnection}
                loading={testResults.database === 'testing'}
                style={{ marginRight: '8px' }}
              >
                {t('settings.test_database_connection')}
              </Button>
              {testResults.database === 'success' && (
                <Text type="success">{t('settings.connection_success')}</Text>
              )}
              {testResults.database === 'failed' && (
                <Text type="danger">{t('settings.connection_failed')}</Text>
              )}
            </Form.Item>
          </Card> */}

          <Divider />

          <Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                icon={<SaveOutlined />}
                loading={saveLoading}
              >
                {t('settings.save_settings')}
              </Button>
              <Button type="default" onClick={resetSettings} icon={<ReloadOutlined />}>
                {t('settings.reset_settings')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}

export default Setting
