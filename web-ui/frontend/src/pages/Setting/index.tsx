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
  Checkbox,
  Switch,
  InputNumber
} from 'antd'
import {
  SettingOutlined,
  KeyOutlined,
  DatabaseOutlined,
  ApiOutlined,
  SaveOutlined,
  ReloadOutlined,
  GlobalOutlined,
  AppstoreOutlined,
  PlusOutlined,
  DeleteOutlined
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import LanguageSelector from '../../components/LanguageSelector'
import { SERVER_URL } from '../../utils'
import { authStore } from '../../store/auth'

const { Title, Text } = Typography
const { Option } = Select
const { Password } = Input

const Setting: React.FC = () => {
  const { t } = useTranslation()
  const [form] = Form.useForm()
  const [userKeyForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [availableDatabases, setAvailableDatabases] = useState<any[]>([])
  const [testResults, setTestResults] = useState<any>({})
  const [isCustomEmbedding, setIsCustomEmbedding] = useState(false)
  const [availableDomains, setAvailableDomains] = useState<any[]>([])
  const [userApiKeys, setUserApiKeys] = useState<any[]>([])
  const [userKeyLoading, setUserKeyLoading] = useState(false)
  const [quotaConfig, setQuotaConfig] = useState<any>({
    trial_docs_limit: 3,
    trial_llm_calls_limit: 50,
    trial_embedding_calls_limit: 200
  })
  const [quotaConfigLoading, setQuotaConfigLoading] = useState(false)
  const isAdmin = authStore.user?.role === 'admin'
  const adminOnlyStyle = { marginBottom: '24px', display: isAdmin ? undefined : 'none' }

  // 默认配置
  const defaultSettings = {
    apiKey: '',
    modelProvider: 'openai',
    modelName: 'gpt-3.5-turbo',
    baseUrl: 'https://api.openai.com/v1',
    selectedDatabase: '',
    maxTokens: 2000,
    temperature: 0.7,
    llmTimeout: 600,
    llmModelMaxAsync: 16,
    llmGlobalMaxAsync: 16,
    llmPerKeyMaxAsync: 4,
    llmMaxRetries: 1,
    llmProviderStrategy: 'priority_round_robin',
    llmProviders: [],
    // 嵌入模型配置
    embeddingModel: 'text-embedding-3-small',
    embeddingDim: 1536,
    embeddingBaseUrl: '', // 嵌入模型的API地址
    embeddingApiKey: '', // 嵌入模型的API密钥
    // 新增Mode配置，默认显示所有modes（包含Cog-RAG）
    availableModes: ['llm', 'naive', 'graph', 'hyper', 'hyper-lite', 'cog', 'cog-hybrid', 'cog-entity', 'cog-theme'],
    hyperrag_domain: 'default'
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
    // Qwen3-Embedding 模型 (阿里云百炼)
    {
      value: 'qwen3-embedding-8b',
      label: 'Qwen3-Embedding-8B (阿里云)',
      dim: 4096,
      description: 'Qwen3最新8B嵌入模型，4096维，MTEB多语言第一 (70.58分)，支持100+语言',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'qwen3-embedding-4b',
      label: 'Qwen3-Embedding-4B (阿里云)',
      dim: 2560,
      description: 'Qwen3最新4B嵌入模型，2560维，性能优异 (MTEB: 69.45分)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    {
      value: 'qwen3-embedding-0.6b',
      label: 'Qwen3-Embedding-0.6B (阿里云)',
      dim: 1024,
      description: 'Qwen3最新0.6B轻量级嵌入模型，1024维，高效实用 (MTEB: 64.33分)',
      provider: 'bailian',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    },
    // 硅基流动 Qwen3-Embeddings 模型
    {
      value: 'Qwen/Qwen3-Embedding-8B',
      label: '硅基流动 Qwen3-Embedding-8B',
      dim: 4096,
      description: '硅基流动 Qwen3 8B嵌入模型，4096维，MTEB多语言第一，支持100+语言，最高32768 token',
      provider: 'siliconflow',
      baseUrl: 'https://api.siliconflow.cn/v1'
    },
    {
      value: 'Qwen/Qwen3-Embedding-4B',
      label: '硅基流动 Qwen3-Embedding-4B',
      dim: 2560,
      description: '硅基流动 Qwen3 4B嵌入模型，2560维，性能优异，最高32768 token',
      provider: 'siliconflow',
      baseUrl: 'https://api.siliconflow.cn/v1'
    },
    {
      value: 'Qwen/Qwen3-Embedding-0.6B',
      label: '硅基流动 Qwen3-Embedding-0.6B',
      dim: 1024,
      description: '硅基流动 Qwen3 0.6B轻量级嵌入模型，1024维，高效实用，最高32768 token',
      provider: 'siliconflow',
      baseUrl: 'https://api.siliconflow.cn/v1'
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
      description: '自定义4096维嵌入模型，需要在下方输入具体的模型名称（如：BAAI/bge-large-zh-v1.5）',
      provider: 'custom'
    },
    {
      value: 'custom-2048',
      label: '自定义 2048维模型',
      dim: 2048,
      description: '自定义2048维嵌入模型，需要在下方输入具体的模型名称',
      provider: 'custom'
    },
    {
      value: 'custom-1024',
      label: '自定义 1024维模型',
      dim: 1024,
      description: '自定义1024维嵌入模型，需要在下方输入具体的模型名称',
      provider: 'custom'
    },
    {
      value: 'custom-768',
      label: '自定义 768维模型',
      dim: 768,
      description: '自定义768维嵌入模型，需要在下方输入具体的模型名称',
      provider: 'custom'
    },
    {
      value: 'custom',
      label: '完全自定义',
      dim: 0,
      description: '完全自定义模型名称和维度，维度和模型名称都需要在下方输入',
      provider: 'custom'
    }
  ]

  // 加载设置
  const formatProvidersForForm = (providers: any[] = []) => {
    return providers.map(provider => ({
      ...provider,
      apiKeysText: Array.isArray(provider?.apiKeys)
        ? provider.apiKeys.join('\n')
        : (provider?.apiKeys || '')
    }))
  }

  const formatProvidersForSave = (providers: any[] = []) => {
    return (providers || [])
      .map(provider => {
        const apiKeysText = provider?.apiKeysText || ''
        const apiKeys = Array.isArray(provider?.apiKeys)
          ? provider.apiKeys
          : String(apiKeysText)
            .split(/[\n,;]+/)
            .map(key => key.trim())
            .filter(Boolean)
        return {
          name: provider?.name || '',
          baseUrl: provider?.baseUrl || '',
          modelName: provider?.modelName || '',
          apiKeys,
          enabled: provider?.enabled !== false,
          maxAsync: Number(provider?.maxAsync || 1),
          perKeyMaxAsync: provider?.perKeyMaxAsync ? Number(provider.perKeyMaxAsync) : undefined,
          priority: Number(provider?.priority || 100)
        }
      })
      .filter(provider => provider.name || provider.baseUrl || provider.modelName || provider.apiKeys.length > 0)
  }

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
        console.log('📦 [Settings] 从后端获取的原始设置:', JSON.stringify(settings, null, 2))

        // 处理自定义嵌入模型
        let embeddingModel = settings.embeddingModel || defaultSettings.embeddingModel
        let customEmbeddingModel = settings.customEmbeddingModel || ''

        // 检查是否为自定义模型（不在预定义列表中）
        const isCustomModel = !embeddingModels.find(m => m.value === embeddingModel)

        // 检查是否选择了自定义选项（以custom开头）
        const isCustomOption = embeddingModel.startsWith('custom')

        // 如果是完全自定义或者有自定义模型名称，则显示模型名称输入框
        if (isCustomModel || isCustomOption || customEmbeddingModel) {
          if (isCustomModel) {
            // 如果是完全自定义（不在列表中），将模型名称保存到customEmbeddingModel
            customEmbeddingModel = embeddingModel
            embeddingModel = 'custom'
          }
          setIsCustomEmbedding(true)
        } else {
          setIsCustomEmbedding(false)
          customEmbeddingModel = ''
        }

        const finalSettings = {
          ...defaultSettings,
          ...settings,
          ...modeSettings,
          embeddingModel,
          customEmbeddingModel,
          llmProviders: formatProvidersForForm(settings.llmProviders || [])
        }
        console.log('🎯 [Settings] 最终设置的表单值:', JSON.stringify(finalSettings, null, 2)) // 调试日志

        form.setFieldsValue(finalSettings)
        console.log('✅ [Settings] 表单值已设置')
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

  // 加载可用领域列表
  const loadDomains = async () => {
    try {
      const response = await fetch(`${SERVER_URL}/domains`)
      if (response.ok) {
        const data = await response.json()
        setAvailableDomains(data.domains || [])
      }
    } catch (error) {
      console.error('加载领域列表失败:', error)
      setAvailableDomains([
        { name: 'default', description: '通用领域（分隔符格式）', output_format: 'delimiter' }
      ])
    }
  }

  // 保存设置
  const saveSettings = async (values: any) => {
    setSaveLoading(true)
    try {
      // 分离Mode设置和其他设置
      const { availableModes, customEmbeddingModel, ...otherSettings } = values

      console.log('💾 保存设置 - 完整表单值:', JSON.stringify(values, null, 2)) // 调试日志
      console.log('💾 保存设置 - availableModes:', availableModes) // 调试日志
      console.log('💾 保存设置 - availableModes 类型:', typeof availableModes) // 调试日志
      console.log('💾 保存设置 - otherSettings:', JSON.stringify(otherSettings, null, 2)) // 调试日志

      // 处理自定义嵌入模型
      let finalEmbeddingModel = otherSettings.embeddingModel
      if (otherSettings.embeddingModel === 'custom' && customEmbeddingModel) {
        finalEmbeddingModel = customEmbeddingModel
        console.log('💾 使用自定义嵌入模型:', finalEmbeddingModel)
      }

      const settingsToSave = {
        ...otherSettings,
        embeddingModel: finalEmbeddingModel,
        llmProviders: formatProvidersForSave(otherSettings.llmProviders || [])
      }

      console.log('💾 准备保存的完整设置:', JSON.stringify(settingsToSave, null, 2))

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
        embeddingModel: finalEmbeddingModel,
        llmProviders: formatProvidersForSave(otherSettings.llmProviders || [])
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
  const testProviderConnection = async (index: number) => {
    const values = form.getFieldsValue()
    const providers = formatProvidersForSave(values.llmProviders || [])
    const provider = providers[index]
    if (!provider || !provider.apiKeys?.length) {
      message.error('Please enter at least one provider API key')
      return
    }

    setTestResults({ ...testResults, [`provider-${index}`]: 'testing' })
    try {
      const response = await fetch(`${SERVER_URL}/test-api`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          apiKey: provider.apiKeys[0],
          baseUrl: provider.baseUrl,
          modelName: provider.modelName,
          modelProvider: 'openai'
        })
      })

      if (response.ok) {
        const result = await response.json()
        if (result.success) {
          setTestResults({ ...testResults, [`provider-${index}`]: 'success' })
          message.success('Provider connection succeeded')
        } else {
          setTestResults({ ...testResults, [`provider-${index}`]: 'failed' })
          message.error(result.message || 'Provider connection failed')
        }
      } else {
        setTestResults({ ...testResults, [`provider-${index}`]: 'failed' })
        message.error('Provider connection failed')
      }
    } catch (error: any) {
      setTestResults({ ...testResults, [`provider-${index}`]: 'failed' })
      message.error('Provider connection failed: ' + error.message)
    }
  }

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
      // 检查是否为自定义模型（完全自定义或自定义维度选项）
      const isCustom = value === 'custom' || value.startsWith('custom-')
      setIsCustomEmbedding(isCustom)

      // 清空自定义模型名称，除非是完全自定义选项
      if (value !== 'custom') {
        form.setFieldsValue({ customEmbeddingModel: '' })
      }

      if (!isCustom) {
        form.setFieldsValue({
          embeddingDim: model.dim // 自动设置对应的维度
        })

        // 如果是阿里云百炼模型，自动设置base_url
        if (model.provider === 'bailian' && model.baseUrl) {
          form.setFieldsValue({
            embeddingBaseUrl: model.baseUrl
          })
          message.info(`已自动设置阿里云百炼API地址，请配置您的阿里云百炼API Key`)
        } else if (model.provider === 'siliconflow' && model.baseUrl) {
          form.setFieldsValue({
            embeddingBaseUrl: model.baseUrl
          })
          message.info(`已自动设置硅基流动API地址，请配置您的硅基流动API Key`)
        }
      }
    }
  }

  const loadUserApiKeys = async () => {
    try {
      const response = await fetch(`${SERVER_URL}/user-api-keys`)
      if (response.ok) {
        const data = await response.json()
        setUserApiKeys(data.keys || [])
      }
    } catch (error) {
      console.error('加载用户 API Key 失败:', error)
    }
  }

  const saveUserApiKey = async (values: any) => {
    setUserKeyLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/user-api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values)
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || data.message || '保存失败')
      }
      message.success('个人 API Key 已保存')
      userKeyForm.resetFields()
      await loadUserApiKeys()
      await authStore.refreshQuota()
    } catch (error: any) {
      message.error(error.message || '保存个人 API Key 失败')
    } finally {
      setUserKeyLoading(false)
    }
  }

  const deleteUserApiKey = async (id: string) => {
    try {
      const response = await fetch(`${SERVER_URL}/user-api-keys/${id}`, {
        method: 'DELETE'
      })
      if (!response.ok) {
        throw new Error('删除失败')
      }
      message.success('已删除个人 API Key')
      await loadUserApiKeys()
    } catch (error: any) {
      message.error(error.message || '删除失败')
    }
  }

  const loadQuotaConfig = async () => {
    if (authStore.user?.role !== 'admin') {
      return
    }
    try {
      const response = await fetch(`${SERVER_URL}/admin/quota-config`)
      if (response.ok) {
        const data = await response.json()
        setQuotaConfig(data.quota_config || quotaConfig)
      }
    } catch (error) {
      console.error('加载额度配置失败:', error)
    }
  }

  const saveQuotaConfig = async () => {
    setQuotaConfigLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/admin/quota-config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(quotaConfig)
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.detail || data.message || '保存额度配置失败')
      }
      setQuotaConfig(data.quota_config || quotaConfig)
      message.success('默认试用额度已更新')
    } catch (error: any) {
      message.error(error.message || '保存额度配置失败')
    } finally {
      setQuotaConfigLoading(false)
    }
  }

  useEffect(() => {
    loadSettings()
    loadDatabases()
    loadDomains()
    authStore.refreshQuota()
    loadUserApiKeys()
    loadQuotaConfig()
  }, [authStore.user?.role])

  return (
    <div className="p-6">
      <Card className="border-gray-200 rounded-xl">
        <div className="mb-4">
          <div className="flex items-center text-2xl font-bold">
            <SettingOutlined style={{ marginRight: '8px' }} />
            {t('settings.title')}
          </div>
          <Text type="secondary">{t('settings.subtitle')}</Text>
        </div>

        <Form form={form} layout="vertical" onFinish={saveSettings} initialValues={defaultSettings}>
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

          {isAdmin && (
            <Card
              title={
                <span>
                  <KeyOutlined style={{ marginRight: '8px' }} />
                  Admin trial quota
                </span>
              }
              style={{ marginBottom: '24px' }}
            >
              <Alert
                message="Default quota for non-admin users"
                description="Admin accounts are not charged against trial quotas. These values only apply when ordinary users use the platform default API pool."
                type="info"
                showIcon
                style={{ marginBottom: '16px' }}
              />
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label="Document embedding quota">
                    <InputNumber
                      min={0}
                      max={1000000}
                      style={{ width: '100%' }}
                      value={quotaConfig.trial_docs_limit}
                      onChange={(value) => setQuotaConfig({ ...quotaConfig, trial_docs_limit: Number(value || 0) })}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="LLM QA quota">
                    <InputNumber
                      min={0}
                      max={1000000}
                      style={{ width: '100%' }}
                      value={quotaConfig.trial_llm_calls_limit}
                      onChange={(value) => setQuotaConfig({ ...quotaConfig, trial_llm_calls_limit: Number(value || 0) })}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="Embedding call quota">
                    <InputNumber
                      min={0}
                      max={1000000}
                      style={{ width: '100%' }}
                      value={quotaConfig.trial_embedding_calls_limit}
                      onChange={(value) => setQuotaConfig({ ...quotaConfig, trial_embedding_calls_limit: Number(value || 0) })}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" loading={quotaConfigLoading} onClick={saveQuotaConfig}>
                Save trial quota
              </Button>
            </Card>
          )}

          <Card
            title={
              <span>
                <KeyOutlined style={{ marginRight: '8px' }} />
                HyperChE 试用额度与个人 API Key
              </span>
            }
            style={{ marginBottom: '24px' }}
          >
            <Alert
              message="个人 API Key 优先"
              description="未配置个人 Key 时，HyperChE 使用平台试用额度；配置个人 LLM 或 embedding Key 后，对应调用将优先使用你的 Key，并不扣平台试用额度。"
              type="info"
              showIcon
              style={{ marginBottom: '16px' }}
            />

            {authStore.quota && (
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <Text type="secondary">文档嵌入</Text>
                    <div className="mt-1 text-xl font-semibold text-slate-900">
                      {authStore.quota.trial_docs_used}/{authStore.quota.trial_docs_limit}
                    </div>
                  </div>
                </Col>
                <Col span={8}>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <Text type="secondary">LLM 问答</Text>
                    <div className="mt-1 text-xl font-semibold text-slate-900">
                      {authStore.quota.trial_llm_calls_used}/{authStore.quota.trial_llm_calls_limit}
                    </div>
                  </div>
                </Col>
                <Col span={8}>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <Text type="secondary">Embedding 调用</Text>
                    <div className="mt-1 text-xl font-semibold text-slate-900">
                      {authStore.quota.trial_embedding_calls_used}/{authStore.quota.trial_embedding_calls_limit}
                    </div>
                  </div>
                </Col>
              </Row>
            )}

            <Form
              form={userKeyForm}
              layout="vertical"
              component={false}
              initialValues={{ provider_type: 'llm', enabled: true }}
            >
              <Row gutter={16}>
                <Col span={4}>
                  <Form.Item name="provider_type" label="类型" rules={[{ required: true }]}>
                    <Select>
                      <Option value="llm">LLM</Option>
                      <Option value="embedding">Embedding</Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={7}>
                  <Form.Item name="base_url" label="Base URL" rules={[{ required: true, message: '请输入 Base URL' }]}>
                    <Input placeholder="https://api.siliconflow.cn/v1" />
                  </Form.Item>
                </Col>
                <Col span={6}>
                  <Form.Item name="model_name" label="Model Name" rules={[{ required: true, message: '请输入模型名' }]}>
                    <Input placeholder="deepseek-ai/DeepSeek-V4-Flash" />
                  </Form.Item>
                </Col>
                <Col span={7}>
                  <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
                    <Input.TextArea
                      rows={4}
                      placeholder={'sk-xxxxxxxxxxxxxxxx\nsk-yyyyyyyyyyyyyyyy'}
                      autoSize={{ minRows: 3, maxRows: 8 }}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="enabled" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
              <Button
                type="primary"
                loading={userKeyLoading}
                onClick={async () => {
                  const values = await userKeyForm.validateFields()
                  await saveUserApiKey(values)
                }}
              >
                保存个人 API Key
              </Button>
            </Form>

            <Divider />
            <Space direction="vertical" style={{ width: '100%' }}>
              {userApiKeys.length === 0 ? (
                <Text type="secondary">暂无个人 API Key。配置后系统会优先使用个人 Key。</Text>
              ) : (
                userApiKeys.map(item => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3"
                  >
                    <div>
                      <div className="text-sm font-medium text-slate-900">
                        {item.provider_type.toUpperCase()} · {item.model_name}
                      </div>
                      <div className="text-xs text-slate-500">
                        {item.base_url}
                        {item.api_key_count ? ` · ${item.api_key_count} keys` : ''}
                      </div>
                    </div>
                    <Space>
                      <Text type={item.enabled ? 'success' : 'secondary'}>{item.enabled ? '启用' : '停用'}</Text>
                      <Button danger type="text" onClick={() => deleteUserApiKey(item.id)}>
                        删除
                      </Button>
                    </Space>
                  </div>
                ))
              )}
            </Space>
          </Card>

          {/* API 配置区块 */}
          <Card
            title={
              <span>
                <ApiOutlined style={{ marginRight: '8px' }} />
                {t('settings.api_config')}
              </span>
            }
            style={adminOnlyStyle}
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
                <ApiOutlined style={{ marginRight: '8px' }} />
                LLM Provider Pool
              </span>
            }
            style={adminOnlyStyle}
          >
            <Alert
              message="LLM Provider Pool"
              description="Configure multiple OpenAI-compatible providers. If this list is empty, the legacy Base URL, model name, and API key fields above are used."
              type="info"
              showIcon
              style={{ marginBottom: '16px' }}
            />

            <Row gutter={16}>
              <Col span={6}>
                <Form.Item name="llmGlobalMaxAsync" label="Global Max Async">
                  <InputNumber min={1} max={32} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="llmPerKeyMaxAsync" label="Per Key Max Async">
                  <InputNumber min={1} max={8} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="llmMaxRetries" label="Max Retries">
                  <InputNumber min={0} max={5} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="llmTimeout" label="Timeout (s)">
                  <InputNumber min={30} max={1800} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>

            <Form.List name="llmProviders">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <div
                      key={key}
                      style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 16, marginBottom: 12 }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                        <Text strong>{`Provider ${name + 1}`}</Text>
                        <Space>
                          <Button
                            size="small"
                            onClick={() => testProviderConnection(name)}
                            loading={testResults[`provider-${name}`] === 'testing'}
                          >
                            Test
                          </Button>
                          <Button danger type="text" icon={<DeleteOutlined />} onClick={() => remove(name)} />
                        </Space>
                      </div>
                      <Row gutter={16}>
                        <Col span={8}>
                          <Form.Item {...restField} name={[name, 'name']} label="Name">
                            <Input placeholder="siliconflow-deepseek" />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item {...restField} name={[name, 'baseUrl']} label="Base URL">
                            <Input placeholder="https://api.siliconflow.cn/v1" />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item {...restField} name={[name, 'modelName']} label="Model Name">
                            <Input placeholder="deepseek-ai/DeepSeek-V4-Flash" />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Row gutter={16}>
                        <Col span={8}>
                          <Form.Item {...restField} name={[name, 'apiKeysText']} label="API Keys">
                            <Input.TextArea rows={4} placeholder="One API key per line" />
                          </Form.Item>
                        </Col>
                        <Col span={4}>
                          <Form.Item {...restField} name={[name, 'enabled']} label="Enabled" valuePropName="checked">
                            <Switch />
                          </Form.Item>
                        </Col>
                        <Col span={4}>
                          <Form.Item {...restField} name={[name, 'maxAsync']} label="Provider Max">
                            <InputNumber min={1} max={32} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={4}>
                          <Form.Item {...restField} name={[name, 'perKeyMaxAsync']} label="Per Key Max">
                            <InputNumber min={1} max={8} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={4}>
                          <Form.Item {...restField} name={[name, 'priority']} label="Priority">
                            <InputNumber min={0} max={999} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                    </div>
                  ))}
                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() => add({
                      name: '',
                      baseUrl: '',
                      modelName: '',
                      apiKeysText: '',
                      enabled: true,
                      maxAsync: 1,
                      perKeyMaxAsync: 1,
                      priority: 100
                    })}
                    block
                  >
                    Add Provider
                  </Button>
                </>
              )}
            </Form.List>
          </Card>

          <Card
            title={
              <span>
                <DatabaseOutlined style={{ marginRight: '8px' }} />
                嵌入模型配置
              </span>
            }
            style={adminOnlyStyle}
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
                    extra={
                      <div>
                        <p>请输入你要使用的嵌入模型名称，例如：</p>
                        <ul style={{ marginLeft: '20px', marginTop: '4px' }}>
                          <li>BAAI/bge-large-zh-v1.5 (中文模型)</li>
                          <li>BAAI/bge-m3 (多语言模型)</li>
                          <li>netease-youdao/bce-embedding-base_v1 (网易有道)</li>
                          <li>your-custom-model (自定义模型)</li>
                        </ul>
                        <p style={{ marginTop: '4px' }}>请确保该模型在您的API提供商处可用，并且维度与上方设置一致。</p>
                      </div>
                    }
                  >
                    <Input placeholder="例如：BAAI/bge-large-zh-v1.5" />
                  </Form.Item>
                </Col>
              </Row>
            )}

            {/* 嵌入API配置说明 */}
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
                  <p style={{ marginTop: '8px' }}><strong>硅基流动配置：</strong></p>
                  <ul style={{ marginLeft: '20px', marginTop: '8px' }}>
                    <li>Base URL: https://api.siliconflow.cn/v1</li>
                    <li>API Key: 从硅基流动控制台获取的API-KEY</li>
                    <li>官方文档: <a href="https://docs.siliconflow.cn/cn/api-reference/embeddings/create-embeddings" target="_blank" rel="noopener noreferrer">查看文档</a></li>
                    <li>Qwen3-Embedding-8B: 高性能中文嵌入模型，4096维，支持32768 token</li>
                  </ul>
                  <p style={{ marginTop: '8px' }}><strong>其他自定义API：</strong></p>
                  <p style={{ marginLeft: '20px', marginTop: '4px' }}>请根据您的API提供商填写相应的Base URL和API Key</p>
                </div>
              }
              type="info"
              showIcon
              style={{ marginBottom: '16px' }}
            />

            {/* 嵌入API配置 */}
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item
                  name="embeddingBaseUrl"
                  label="嵌入API Base URL"
                  rules={[{ required: true, message: '请输入嵌入API的Base URL' }]}
                  extra="嵌入模型的API端点，例如：https://api.siliconflow.cn/v1"
                >
                  <Input placeholder="https://api.siliconflow.cn/v1" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item
                  name="embeddingApiKey"
                  label="嵌入API Keys"
                  rules={[{ required: true, message: '请输入嵌入API的Key' }]}
                  extra="支持多个嵌入 API Key：每行一个，也可用逗号或分号分隔。调用失败时会自动轮换到下一个 Key。"
                >
                  <Input.TextArea
                    rows={4}
                    placeholder={'sk-xxxxxxxxxxxxxxxx\nsk-yyyyyyyyyyyyyyyy'}
                    autoSize={{ minRows: 3, maxRows: 8 }}
                  />
                </Form.Item>
              </Col>
            </Row>

            <Alert
              message="重要提示"
              description="更换嵌入模型后，需要清空现有数据库重新嵌入文档，否则会因维度不匹配导致错误。"
              type="error"
              showIcon
              style={{ marginTop: '16px' }}
            />
          </Card>

          {/* 嵌入领域配置区块 */}
          <Card
            title={
              <span>
                <AppstoreOutlined style={{ marginRight: '8px' }} />
                嵌入领域配置
              </span>
            }
            style={adminOnlyStyle}
          >
            <Alert
              message="嵌入领域配置"
              description="选择文档嵌入时使用的知识提取领域。不同领域使用不同的实体类型、关系类型和输出格式。更换领域后需要清空数据库重新嵌入文档。"
              type="info"
              showIcon
              style={{ marginBottom: '24px' }}
            />
            <Form.Item
              name="hyperrag_domain"
              label="嵌入领域"
              extra="选择文档嵌入时使用的知识提取领域"
            >
              <Select placeholder="选择嵌入领域">
                {availableDomains.map(domain => (
                  <Option key={domain.name} value={domain.name}>
                    <div>
                      <div style={{ fontWeight: 'bold' }}>
                        {domain.name === 'default' ? '通用领域 (Default)' : domain.name}
                      </div>
                      <div style={{ fontSize: '12px', color: '#666' }}>
                        {domain.description || '无描述'} | 输出格式: {domain.output_format}
                      </div>
                    </div>
                  </Option>
                ))}
              </Select>
            </Form.Item>
            <Alert
              message="注意"
              description="切换领域后，已有的嵌入数据不会自动更新。建议新建数据库并用新领域重新嵌入文档。"
              type="warning"
              showIcon
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

          <Form.Item style={{ display: isAdmin ? undefined : 'none' }}>
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
