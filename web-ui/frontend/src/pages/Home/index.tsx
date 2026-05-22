import React, { useState, useEffect } from 'react'
import { observer } from 'mobx-react'
import ReactMarkdown from 'react-markdown'
import {
    MessageCircle,
    Send,
    Plus,
    Database,
    Settings,
    User,
    Bot,
    Trash2,
    RotateCcw,
    Loader2,
    Zap,
    Layers,
    BookOpen,
    GitCompare,
    ChevronDown,
    ChevronRight,
} from 'lucide-react'
import { Tag } from 'antd'
import {
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    ScrollArea,
    Textarea,
    Separator,
    Avatar,
    AvatarFallback,
    AvatarImage
} from '../../components/ui'
import { storeGlobalUser } from '../../store/globalUser'
import { authStore } from '../../store/auth'
import { SERVER_URL } from '../../utils'
import DatabaseSelector from '../../components/DatabaseSelector'
import RetrievalInfo from '../../components/RetrievalInfo'
import RetrievalHyperGraph from '../../components/RetrievalHyperGraph'

const LazyRetrievalGraph = ({
    entities = [],
    hyperedges = [],
    themes = [],
    height = '300px',
    mode = 'hyper',
    graphId = 'retrieval-graph'
}) => {
    const [expanded, setExpanded] = useState(false)
    const entityCount = entities?.length || 0
    const hyperedgeCount = hyperedges?.length || 0
    const themeCount = themes?.length || 0
    const hasGraphData = entityCount > 0 || hyperedgeCount > 0 || themeCount > 0

    if (!hasGraphData) {
        return null
    }

    return (
        <div className="mt-4 rounded-md border border-gray-200 bg-white">
            <button
                type="button"
                onClick={() => setExpanded(prev => !prev)}
                className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
            >
                <span className="flex items-center gap-2 font-medium">
                    {expanded ? (
                        <ChevronDown className="h-4 w-4" />
                    ) : (
                        <ChevronRight className="h-4 w-4" />
                    )}
                    Retrieval hypergraph visualization
                </span>
                <span className="text-xs text-gray-500">
                    {entityCount} entities | {hyperedgeCount} hyperedges
                    {themeCount > 0 ? ` | ${themeCount} themes` : ''}
                </span>
            </button>

            {expanded && (
                <div className="border-t border-gray-200 p-3">
                    <RetrievalHyperGraph
                        entities={entities}
                        hyperedges={hyperedges}
                        themes={themes}
                        height={height}
                        mode={mode}
                        graphId={graphId}
                    />
                </div>
            )}
        </div>
    )
}

const HyperRAGHome = () => {
    // State
    const [conversations, setConversations] = useState([])
    const [activeConversationId, setActiveConversationId] = useState('')
    const [inputValue, setInputValue] = useState('')
    const [queryMode, setQueryMode] = useState('hyper')
    const [isLoading, setIsLoading] = useState(false)
    const [availableModes, setAvailableModes] = useState(['naive', 'graph', 'hyper'])

    // 新增：RAG系统状态管理
    const [currentRAGSystem, setCurrentRAGSystem] = useState('hyperrag')
    const [systemsStatus, setSystemsStatus] = useState(null)

    // 新增对比模式相关状态
    const [isCompareMode, setIsCompareMode] = useState(false)
    const [compareMode1, setCompareMode1] = useState('hyper')
    const [compareMode2, setCompareMode2] = useState('naive')

    // Storage keys
    const storageScope = authStore.user?.id || authStore.user?.email || 'anonymous'
    const STORAGE_KEYS = {
        CONVERSATIONS: `hyperrag_conversations_v3_${storageScope}`,
        ACTIVE_ID: `hyperrag_active_conversation_v3_${storageScope}`
    }

    // 定义所有可用的模式配置
    const allModes = [
        { value: 'llm', label: 'LLM', icon: Bot, color: 'bg-yellow-500', system: 'hyperrag' },
        { value: 'naive', label: 'RAG', icon: BookOpen, color: 'bg-blue-500', system: 'hyperrag' },
        { value: 'graph', label: 'Graph-RAG', icon: Bot, color: 'bg-orange-500', system: 'hyperrag' },
        { value: 'hyper', label: 'Hyper-RAG', icon: Zap, color: 'bg-purple-500', system: 'hyperrag' },
        { value: 'hyper-lite', label: 'Hyper-RAG-Lite', icon: Layers, color: 'bg-green-500', system: 'hyperrag' },
        // Cog-RAG 模式
        { value: 'cog', label: 'Cog-RAG', icon: GitCompare, color: 'bg-indigo-600', system: 'cograg' },
        { value: 'cog-hybrid', label: 'Cog-Hybrid', icon: GitCompare, color: 'bg-indigo-500', system: 'cograg' },
        { value: 'cog-entity', label: 'Cog-Entity', icon: Bot, color: 'bg-cyan-600', system: 'cograg' },
        { value: 'cog-theme', label: 'Cog-Theme', icon: BookOpen, color: 'bg-teal-600', system: 'cograg' }
    ]

    // 从localStorage加载Mode配置
    const loadModeSettings = () => {
        try {
            const modeSettings = localStorage.getItem('hyperrag_mode_settings')
            console.log('📥 加载模式设置:', modeSettings) // 调试日志

            if (modeSettings) {
                const parsed = JSON.parse(modeSettings)
                console.log('📊 解析后的设置:', parsed) // 调试日志

                if (parsed.availableModes && Array.isArray(parsed.availableModes) && parsed.availableModes.length > 0) {
                    console.log('✅ 设置可用模式:', parsed.availableModes) // 调试日志
                    setAvailableModes(parsed.availableModes)
                    // 如果当前选择的mode不在可用列表中，选择第一个可用的mode
                    if (!parsed.availableModes.includes(queryMode)) {
                        setQueryMode(parsed.availableModes[0])
                        console.log('🔄 切换到第一个可用模式:', parsed.availableModes[0]) // 调试日志
                    }
                } else {
                    console.log('⚠️ 可用模式为空，使用默认配置') // 调试日志
                    // 如果没有配置或配置为空，使用默认配置
                    setAvailableModes(['naive', 'graph', 'hyper'])
                }
            } else {
                console.log('❌ 没有找到模式设置，使用默认配置') // 调试日志
                // 出错时使用默认配置
                setAvailableModes(['naive', 'graph', 'hyper'])
            }
        } catch (error) {
            console.error('Failed to load mode settings:', error)
            // 出错时使用默认配置
            setAvailableModes(['naive', 'graph', 'hyper'])
        }
    }

    // 监听localStorage变化
    const handleStorageChange = (e) => {
        if (e.key === 'hyperrag_mode_settings') {
            loadModeSettings()
        }
    }

    // 获取当前启用的模式列表
    const enabledModes = allModes.filter(mode => availableModes.includes(mode.value))
    console.log('🎯 过滤启用的模式:', {
      allModes: allModes.map(m => m.value),
      availableModes: availableModes,
      enabledModes: enabledModes.map(m => m.value)
    }) // 调试日志

    // 获取模式标签的函数
    const getModeLabel = (roleValue) => {
        if (roleValue === 'user') {
return 'You'
}
        const mode = allModes.find(m => m.value === roleValue)
        return mode ? mode.label : roleValue
    }

    // Utility functions
    const saveToStorage = () => {
        localStorage.setItem(STORAGE_KEYS.CONVERSATIONS, JSON.stringify(conversations))
        localStorage.setItem(STORAGE_KEYS.ACTIVE_ID, activeConversationId)
    }

    const loadFromStorage = () => {
        try {
            const savedConversations = localStorage.getItem(STORAGE_KEYS.CONVERSATIONS)
            const savedActiveId = localStorage.getItem(STORAGE_KEYS.ACTIVE_ID)

            if (savedConversations) {
                const parsed = JSON.parse(savedConversations)
                if (!Array.isArray(parsed) || parsed.length === 0) {
                    const defaultConv = {
                        id: 'default',
                        title: 'New Conversation',
                        messages: [],
                        createdAt: new Date()
                    }
                    setConversations([defaultConv])
                    setActiveConversationId('default')
                    return
                }
                setConversations(parsed)

                if (savedActiveId && parsed.find((c) => c.id === savedActiveId)) {
                    setActiveConversationId(savedActiveId)
                } else if (parsed.length > 0) {
                    setActiveConversationId(parsed[0].id)
                }
            } else {
                // Create default conversation
                const defaultConv = {
                    id: 'default',
                    title: 'Chat 1',
                    messages: [],
                    createdAt: new Date()
                }
                setConversations([defaultConv])
                setActiveConversationId('default')
            }
        } catch (error) {
            console.error('Failed to load from storage:', error)
            const fallbackConv = {
                id: 'default',
                title: 'New Conversation',
                messages: [],
                createdAt: new Date()
            }
            setConversations([fallbackConv])
            setActiveConversationId('default')
        }
    }

    const createNewConversation = () => {
        const newConv = {
            id: Date.now().toString(),
            title: `Chat ${new Date().toLocaleTimeString()}`,
            messages: [],
            createdAt: new Date()
        }
        setConversations(prev => [newConv, ...prev])
        setActiveConversationId(newConv.id)
    }

    const deleteConversation = (id) => {
        setConversations(prev => prev.filter(c => c.id !== id))
        if (activeConversationId === id) {
            const remaining = conversations.filter(c => c.id !== id)
            if (remaining.length > 0) {
                setActiveConversationId(remaining[0].id)
            } else {
                createNewConversation()
            }
        }
    }

    const clearAllChats = () => {
        setConversations([])
        createNewConversation()
    }

    const activeConversation = conversations.find(c => c.id === activeConversationId)

    const addMessage = (content, role, extraData = null) => {
        const newMessage = {
            id: Date.now(),
            content,
            role,
            timestamp: new Date(),
            // 添加检索信息字段
            entities: extraData?.entities || [],
            hyperedges: extraData?.hyperedges || [],
            text_units: extraData?.text_units || [],
            // 新增对比模式字段
            isCompare: extraData?.isCompare || false,
            compareResults: extraData?.compareResults || null
        }

        setConversations(prev =>
            prev.map(conv =>
                conv.id === activeConversationId
                    ? { ...conv, messages: [...conv.messages, newMessage] }
                    : conv
            )
        )
    }

    const updateLastMessage = (content, extraData = null) => {
        setConversations(prev =>
            prev.map(conv =>
                conv.id === activeConversationId
                    ? {
                        ...conv,
                        messages: conv.messages.map((msg, index) =>
                            index === conv.messages.length - 1
                                ? {
                                    ...msg,
                                    content,
                                    // 如果有新的检索信息，更新它们
                                    entities: extraData?.entities || msg.entities || [],
                                    hyperedges: extraData?.hyperedges || msg.hyperedges || [],
                                    text_units: extraData?.text_units || msg.text_units || [],
                                    // 更新对比结果
                                    isCompare: extraData?.isCompare !== undefined ? extraData.isCompare : msg.isCompare,
                                    compareResults: extraData?.compareResults || msg.compareResults
                                }
                                : msg
                        )
                    }
                    : conv
            )
        )
    }

    // 单模式查询函数
    const querySingleMode = async (question, mode) => {
        const response = await fetch(`${SERVER_URL}/hyperrag/query`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                question: question,
                mode: mode,
                top_k: 60,
                max_token_for_text_unit: 1600,
                max_token_for_entity_context: 300,
                max_token_for_relation_context: 1600,
                only_need_context: false,
                response_type: 'Multiple Paragraphs',
                database: storeGlobalUser.selectedDatabase
            }),
        })

        if (!response.ok) {
            throw new Error(`Network error: ${response.status}`)
        }

        const data = await response.json()

        // 确保响应包含Cog-RAG相关字段
        return {
            ...data,
            themes: data.themes || [],  // Cog-RAG的主题信息
            rag_system: data.rag_system || 'hyperrag',  // 使用的RAG系统
        }
    }

    const handleSubmit = async () => {
        if (!inputValue.trim() || isLoading) {
return
}

        const userMessage = inputValue.trim()
        setInputValue('')
        setIsLoading(true)

        // Add user message
        addMessage(userMessage, 'user')

        // 自动根据查询模式切换系统
        const targetSystem = queryMode.startsWith('cog') ? 'cograg' : 'hyperrag'
        if (currentRAGSystem !== targetSystem) {
            setCurrentRAGSystem(targetSystem)
        }

        if (isCompareMode) {
            // 对比模式：同时查询两个模式
            addMessage('正在对比分析中...', 'compare', { isCompare: true })

            try {
                const [result1, result2] = await Promise.all([
                    querySingleMode(userMessage, compareMode1),
                    querySingleMode(userMessage, compareMode2)
                ])

                const modeNames = {
                    'hyper': 'Hyper-RAG',
                    'hyper-lite': 'Hyper-RAG-Lite',
                    'graph': 'Graph-RAG',
                    'naive': 'RAG',
                    'llm': 'LLM',
                }

                const compareResults = {
                    mode1: {
                        name: modeNames[compareMode1] || compareMode1,
                        mode: compareMode1,
                        response: result1.success ? (result1.response || 'No response content') : `Error: ${result1.message}`,
                        entities: result1.entities || [],
                        hyperedges: result1.hyperedges || [],
                        text_units: result1.text_units || [],
                        success: result1.success
                    },
                    mode2: {
                        name: modeNames[compareMode2] || compareMode2,
                        mode: compareMode2,
                        response: result2.success ? (result2.response || 'No response content') : `Error: ${result2.message}`,
                        entities: result2.entities || [],
                        hyperedges: result2.hyperedges || [],
                        text_units: result2.text_units || [],
                        success: result2.success
                    }
                }

                updateLastMessage('对比分析完成', {
                    isCompare: true,
                    compareResults: compareResults
                })

            } catch (error) {
                console.error('Error in compare mode:', error)
                updateLastMessage(`对比分析出错: ${error instanceof Error ? error.message : 'Unknown error'}`, {
                    isCompare: true
                })
            }
        } else {
            // 单模式查询（原有逻辑）
            addMessage('正在思考中...', queryMode)

            try {
                const data = await querySingleMode(userMessage, queryMode)

                if (data.success) {
                    const modeNames = {
                        // HyperRAG 模式
                        'hyper': 'Hyper-RAG',
                        'hyper-lite': 'Hyper-RAG-Lite',
                        'graph': 'Graph-RAG',
                        'naive': 'RAG',
                        'llm': 'LLM',
                        // Cog-RAG 模式
                        'cog': 'Cog-RAG',
                        'cog-hybrid': 'Cog-Hybrid',
                        'cog-entity': 'Cog-Entity',
                        'cog-theme': 'Cog-Theme'
                    }
                    const modeName = modeNames[queryMode] || queryMode

                    // 获取系统信息
                    const modeInfo = allModes.find(m => m.value === queryMode)
                    const systemName = modeInfo?.system === 'cograg' ? 'Cog-RAG' : 'HyperRAG'

                    let responseContent = data.response || 'No response content'
                    responseContent += `\n\n---\n*${systemName} - ${modeName}*`

                    updateLastMessage(responseContent, {
                        entities: data.entities || [],
                        hyperedges: data.hyperedges || [],
                        text_units: data.text_units || [],
                        themes: data.themes || [],  // 添加Cog-RAG的主题信息
                        rag_system: data.rag_system || 'hyperrag'  // 添加系统标识
                    })
                } else {
                    throw new Error(data.message || 'Query failed')
                }
            } catch (error) {
                console.error('Error sending message:', error)
                updateLastMessage(`Sorry, an error occurred: ${error instanceof Error ? error.message : 'Unknown error'}`)
            }
        }

        setIsLoading(false)
    }

    const handleKeyPress = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSubmit()
        }
    }

    // Effects
    useEffect(() => {
        storeGlobalUser.restoreSelectedDatabase()
        storeGlobalUser.loadDatabases()
        loadFromStorage()
        loadModeSettings()

        // 获取系统状态
        fetch(`${SERVER_URL}/systems/status`)
            .then(response => response.json())
            .then(data => {
                setSystemsStatus(data)
            })
            .catch(error => {
                console.error('Failed to load systems status:', error)
            })

        // 添加storage事件监听器
        window.addEventListener('storage', handleStorageChange)

        return () => {
            window.removeEventListener('storage', handleStorageChange)
        }
    }, [storageScope])

    useEffect(() => {
        if (conversations.length > 0) {
            saveToStorage()
        }
    }, [conversations, activeConversationId, storageScope])

    // 当availableModes变化时，确保当前选择的mode在可用列表中
    useEffect(() => {
        if (availableModes.length > 0 && !availableModes.includes(queryMode)) {
            setQueryMode(availableModes[0])
        }
    }, [availableModes, queryMode])

    // 当对比模式切换时，确保选择的模式在可用列表中
    useEffect(() => {
        if (availableModes.length > 0) {
            if (!availableModes.includes(compareMode1)) {
                setCompareMode1(availableModes[0])
            }
            if (!availableModes.includes(compareMode2)) {
                setCompareMode2(availableModes[Math.min(1, availableModes.length - 1)])
            }
        }
    }, [availableModes, compareMode1, compareMode2])

    return (
        <div className="flex h-screen bg-gray-50">
            {/* Sidebar */}
            <div className="w-52 bg-gray-100 border-r border-gray-200 flex flex-col">

                {/* Mode Selector */}
                <div className="flex items-center space-x-1 p-3 text-base">
                    <div className="flex flex-col bg-gray-100 rounded-lg p-1 w-full space-y-1">
                        <div className="flex items-center space-x-2 mb-3">
                            <Settings className="w-5 h-5 shrink-0 text-gray-500" />
                            <span className="font-medium text-gray-700 flex-1">Mode: </span>
                            {/* 对比模式开关 */}
                            <div className=" p-2 bg-white rounded-md">
                                <label className="flex items-center cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={isCompareMode}
                                        onChange={(e) => setIsCompareMode(e.target.checked)}
                                        className="rounded"
                                    />
                                    <span className="text-sm font-medium text-gray-700 ml-1">对比</span>
                                    <GitCompare className="w-4 h-4 text-blue-500" />
                                </label>
                            </div>
                        </div>


                        {isCompareMode ? (
                            /* 对比模式：显示两个模式选择器 */
                            <div className="space-y-3">
                                <div>
                                    <span className="text-xs text-gray-500 mb-1 block">Mode 1:</span>
                                    <div className="space-y-1">
                                        {enabledModes.map((mode) => {
                                            const IconComponent = mode.icon
                                            return (
                                                <button
                                                    key={`mode1-${mode.value}`}
                                                    onClick={() => setCompareMode1(mode.value)}
                                                    className={`text-base flex items-center space-x-2 px-3 py-1.5 rounded-md font-medium transition-all duration-200 cursor-pointer w-full ${compareMode1 === mode.value
                                                        ? `${mode.color} text-white shadow-md`
                                                        : 'text-gray-600 hover:bg-gray-200'
                                                        }`}
                                                >
                                                    <IconComponent className="w-3 h-3 shrink-0" />
                                                    <span>{mode.label}</span>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>
                                <div>
                                    <span className="text-xs text-gray-500 mb-1 block">Mode 2:</span>
                                    <div className="space-y-1">
                                        {enabledModes.map((mode) => {
                                            const IconComponent = mode.icon
                                            return (
                                                <button
                                                    key={`mode2-${mode.value}`}
                                                    onClick={() => setCompareMode2(mode.value)}
                                                    className={`text-base flex items-center space-x-2 px-3 py-1.5 rounded-md font-medium transition-all duration-200 cursor-pointer w-full ${compareMode2 === mode.value
                                                        ? `${mode.color} text-white shadow-md`
                                                        : 'text-gray-600 hover:bg-gray-200'
                                                        }`}
                                                >
                                                    <IconComponent className="w-3 h-3 shrink-0" />
                                                    <span>{mode.label}</span>
                                                </button>
                                            )
                                        })}
                                    </div>
                                </div>
                            </div>
                        ) : (
                            /* 单模式：显示原有的模式选择器 */
                            enabledModes.map((mode) => {
                                const IconComponent = mode.icon
                                return (
                                    <button
                                        key={mode.value}
                                        onClick={() => setQueryMode(mode.value)}
                                        className={`text-base flex items-center space-x-2 px-4 py-2 rounded-md font-medium transition-all duration-200 cursor-pointer ${queryMode === mode.value
                                            ? `${mode.color} text-white shadow-md`
                                            : 'text-gray-600 hover:bg-gray-200'
                                            }`}
                                    >
                                        <IconComponent className="w-4 h-4 shrink-0" />
                                        <span>{mode.label}</span>
                                    </button>
                                )
                            })
                        )}
                    </div>
                </div>

                {/* 系统状态指示器 */}
                <div className="mx-3 mt-4 p-3 bg-white rounded-lg border border-gray-200">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                            {currentRAGSystem === 'cograg' ? (
                                <GitCompare className="w-4 h-4 text-purple-500" />
                            ) : (
                                <Zap className="w-4 h-4 text-blue-500" />
                            )}
                            <span className="text-sm font-medium text-gray-700">
                                当前使用：{currentRAGSystem === 'cograg' ? 'Cog-RAG' : 'HyperRAG'} 系统
                            </span>
                        </div>
                        {systemsStatus && (
                            <Tag color={currentRAGSystem === 'cograg' ? 'purple' : 'blue'} className="text-xs">
                                {currentRAGSystem === 'cograg'
                                    ? `${systemsStatus.cograg.instances} 实例`
                                    : `${systemsStatus.hyperrag.instances} 实例`}
                            </Tag>
                        )}
                    </div>
                </div>

                {/* Header */}
                <Separator className="my-3" />
                <div className="p-4 border-b border-gray-200">
                    <Button
                        onClick={createNewConversation}
                        className="w-full"
                        variant="outline"
                    >
                        <Plus className="w-4 h-4 mr-2" />
                        New Conversation
                    </Button>
                </div>

                {/* Conversations List */}
                <ScrollArea className="flex-1 p-2">
                    <div className="space-y-2">
                        {conversations.map((conv) => (
                            <div
                                key={conv.id}
                                className={`group p-1 rounded-lg cursor-pointer transition-colors ${activeConversationId === conv.id
                                    ? 'bg-blue-50 border border-blue-200'
                                    : 'hover:bg-gray-50'
                                    }`}
                                onClick={() => setActiveConversationId(conv.id)}
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center space-x-2 flex-1 min-w-0">
                                        <MessageCircle className="w-4 h-4 text-gray-500" />
                                        <span className="text-sm font-medium text-gray-900 truncate">
                                            {conv.title}
                                        </span>
                                    </div>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="opacity-0 group-hover:opacity-100 h-6 w-6"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            deleteConversation(conv.id)
                                        }}
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </Button>
                                </div>

                            </div>
                        ))}
                    </div>
                </ScrollArea>

                {/* Controls */}
                <div className="p-4 border-t border-gray-200 space-y-4">
                    <Button
                        variant="outline"
                        onClick={clearAllChats}
                        className="w-full"
                    >
                        <RotateCcw className="w-4 h-4 mr-2" />
                        Clear All Chats
                    </Button>
                </div>

            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col">
                {/* Top Bar */}
                <div className="bg-white border-b border-gray-200 p-4">
                    <div className="flex items-center justify-between w-full">
                        <div className="flex items-center space-x-4">
                            <Database className="w-5 h-5 text-gray-500" />
                            <span className="font-medium text-gray-700">Database:</span>
                            <DatabaseSelector
                                mode="select"
                                showRefresh={true}
                                placeholder="选择数据库"
                                style={{}}
                                size="middle"
                                disabled={false}
                            />
                        </div>
                    </div>
                </div>

                {/* Chat Area */}
                <div className="flex-1 flex flex-col">
                    {/* Messages */}
                    <ScrollArea className="p-4 pb-0 h-[calc(100vh-210px)] bg-white">
                        {activeConversation?.messages.length === 0 ? (
                            <div className="flex-1 flex items-center justify-center mt-20">
                                <div className="text-center">
                                    <Bot className="w-16 h-16 text-gray-400 mx-auto mb-4" />
                                    <h3 className="text-lg font-medium text-gray-900 mb-2">
                                        Welcome to Hyper-RAG
                                    </h3>
                                    <p className="text-gray-500 max-w-md">
                                        Ask me anything about your knowledge base. I&apos;ll help you find the
                                        information you need using advanced RAG technology.
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <div className="space-y-6 mx-auto">
                                {activeConversation?.messages.map((message) => (
                                    <div key={message.id + message.content} className="flex space-x-4">
                                        <Avatar>
                                            {message.role === 'user' ? (
                                                <AvatarFallback>
                                                    <User className="w-5 h-5" />
                                                </AvatarFallback>
                                            ) : (
                                                <AvatarFallback>
                                                    {message.isCompare ? (
                                                        <GitCompare className="w-5 h-5" />
                                                    ) : (
                                                        <Bot className="w-5 h-5" />
                                                    )}
                                                </AvatarFallback>
                                            )}
                                        </Avatar>

                                        <div className="flex-1 space-y-2">
                                            <div className="flex items-center space-x-2">
                                                <span className="font-medium text-gray-900">
                                                    {message.isCompare ? '对比分析' : getModeLabel(message.role)}
                                                </span>
                                                {/* 系统标识标签 */}
                                                {message.rag_system === 'cograg' && (
                                                    <Tag color="purple" className="ml-2">Cog-RAG</Tag>
                                                )}
                                                {message.rag_system === 'hyperrag' && (
                                                    <Tag color="blue" className="ml-2">HyperRAG</Tag>
                                                )}
                                                <span className="text-xs text-gray-500">
                                                    {new Date(message.timestamp).toLocaleTimeString()}
                                                </span>
                                            </div>

                                            {message.isCompare && message.compareResults ? (
                                                /* 对比模式的消息展示 */
                                                <div className="grid grid-cols-2 gap-4">
                                                    {/* 模式1结果 */}
                                                    <div className="flex flex-col bg-blue-50 border border-blue-200 rounded-lg p-4">
                                                        <div className="flex items-center space-x-2 mb-3">
                                                            <div className="flex items-center space-x-2">
                                                                {(() => {
                                                                    const mode = allModes.find(m => m.value === message.compareResults.mode1.mode)
                                                                    const IconComponent = mode?.icon || Bot
                                                                    return <IconComponent className="w-4 h-4" />
                                                                })()}
                                                                <span className="font-medium text-blue-800">
                                                                    {message.compareResults.mode1.name}
                                                                </span>
                                                            </div>
                                                            {!message.compareResults.mode1.success && (
                                                                <span className="text-xs text-red-500">Failed</span>
                                                            )}
                                                        </div>

                                                        <div className="flex-1 flex flex-col">
                                                            <div className="flex-1 prose prose-sm">
                                                                <ReactMarkdown
                                                                    components={{
                                                                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                                                        code: ({ children, className }) => (
                                                                            <code className={`${className} bg-blue-100 px-1 rounded`}>
                                                                                {children}
                                                                            </code>
                                                                        ),
                                                                        pre: ({ children }) => (
                                                                            <pre className="bg-blue-100 p-3 rounded-md overflow-x-auto">
                                                                                {children}
                                                                            </pre>
                                                                        ),
                                                                    }}
                                                                >
                                                                    {message.compareResults.mode1.response}
                                                                </ReactMarkdown>
                                                            </div>

                                                            {message.compareResults.mode1.success && (
                                                                <div className='overflow-auto pl-2'>
                                                                    <RetrievalInfo
                                                                        entities={message.compareResults.mode1.entities || []}
                                                                        hyperedges={message.compareResults.mode1.hyperedges || []}
                                                                        textUnits={message.compareResults.mode1.text_units || []}
                                                                        mode={message.compareResults.mode1.mode}
                                                                    />

                                                                    {((message.compareResults.mode1.entities && message.compareResults.mode1.entities.length > 0) ||
                                                                        (message.compareResults.mode1.hyperedges && message.compareResults.mode1.hyperedges.length > 0)) && (
                                                                            <LazyRetrievalGraph
                                                                                entities={message.compareResults.mode1.entities || []}
                                                                                hyperedges={message.compareResults.mode1.hyperedges || []}
                                                                                height="300px"
                                                                                mode={message.compareResults.mode1.mode}
                                                                                graphId={`compare-graph-1-${message.id}`}
                                                                            />
                                                                        )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>

                                                    {/* 模式2结果 */}
                                                    <div className="flex flex-col bg-green-50 border border-green-200 rounded-lg p-4">
                                                        <div className="flex items-center space-x-2 mb-3">
                                                            <div className="flex items-center space-x-2">
                                                                {(() => {
                                                                    const mode = allModes.find(m => m.value === message.compareResults.mode2.mode)
                                                                    const IconComponent = mode?.icon || Bot
                                                                    return <IconComponent className="w-4 h-4" />
                                                                })()}
                                                                <span className="font-medium text-green-800">
                                                                    {message.compareResults.mode2.name}
                                                                </span>
                                                            </div>
                                                            {!message.compareResults.mode2.success && (
                                                                <span className="text-xs text-red-500">Failed</span>
                                                            )}
                                                        </div>

                                                        <div className="flex-1 flex flex-col">
                                                            <div className="flex-1 prose prose-sm">
                                                                <ReactMarkdown
                                                                    components={{
                                                                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                                                        code: ({ children, className }) => (
                                                                            <code className={`${className} bg-green-100 px-1 rounded`}>
                                                                                {children}
                                                                            </code>
                                                                        ),
                                                                        pre: ({ children }) => (
                                                                            <pre className="bg-green-100 p-3 rounded-md overflow-x-auto">
                                                                                {children}
                                                                            </pre>
                                                                        ),
                                                                    }}
                                                                >
                                                                    {message.compareResults.mode2.response}
                                                                </ReactMarkdown>
                                                            </div>

                                                            {message.compareResults.mode2.success && (
                                                                <div className='overflow-auto pl-2'>
                                                                    <RetrievalInfo
                                                                        entities={message.compareResults.mode2.entities || []}
                                                                        hyperedges={message.compareResults.mode2.hyperedges || []}
                                                                        textUnits={message.compareResults.mode2.text_units || []}
                                                                        mode={message.compareResults.mode2.mode}
                                                                    />

                                                                    {((message.compareResults.mode2.entities && message.compareResults.mode2.entities.length > 0) ||
                                                                        (message.compareResults.mode2.hyperedges && message.compareResults.mode2.hyperedges.length > 0)) && (
                                                                            <LazyRetrievalGraph
                                                                                entities={message.compareResults.mode2.entities || []}
                                                                                hyperedges={message.compareResults.mode2.hyperedges || []}
                                                                                height="300px"
                                                                                mode={message.compareResults.mode2.mode}
                                                                                graphId={`compare-graph-2-${message.id}`}
                                                                            />
                                                                        )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            ) : (
                                                /* 单模式的消息展示（原有逻辑） */
                                                <div className={`rounded-lg p-4 ${message.role === 'user'
                                                    ? 'bg-blue-50 border border-blue-200'
                                                    : 'bg-gray-50 border border-gray-200'
                                                    }`}>
                                                    {message.role !== 'user' ? (
                                                        <div className='flex'>
                                                            <div className="flex-1 prose prose-sm z-0">
                                                                <ReactMarkdown
                                                                    components={{
                                                                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                                                        code: ({ children, className }) => (
                                                                            <code className={`${className} bg-gray-100 px-1 rounded`}>
                                                                                {children}
                                                                            </code>
                                                                        ),
                                                                        pre: ({ children }) => (
                                                                            <pre className="bg-gray-100 p-3 rounded-md overflow-x-auto">
                                                                                {children}
                                                                            </pre>
                                                                        ),
                                                                    }}
                                                                >
                                                                    {message.content}
                                                                </ReactMarkdown>
                                                            </div>
                                                            <div className='flex-[0.7] overflow-auto pl-2 z-10'>
                                                                {/* 显示检索信息 */}
                                                                <RetrievalInfo
                                                                    entities={message.entities || []}
                                                                    hyperedges={message.hyperedges || []}
                                                                    textUnits={message.text_units || []}
                                                                    themes={message.themes || []}  // 添加主题信息
                                                                    mode={message.role}
                                                                />

                                                                {/* 超图可视化展示 */}
                                                                {((message.entities && message.entities.length > 0) ||
                                                                    (message.hyperedges && message.hyperedges.length > 0) ||
                                                                    (message.themes && message.themes.length > 0)) && (
                                                                        <LazyRetrievalGraph
                                                                            entities={message.entities || []}
                                                                            hyperedges={message.hyperedges || []}
                                                                            themes={message.themes || []}
                                                                            height="400px"
                                                                            mode={message.role}
                                                                            graphId={`retrieval-graph-${message.id}`}
                                                                        />
                                                                    )}
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <p className="text-gray-900 whitespace-pre-wrap m-0">
                                                            {message.content}
                                                        </p>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </ScrollArea>

                    {/* Input Area */}
                    <div className="border-t border-gray-200 bg-white p-2">
                        <div className="max-w-4xl mx-auto">
                            <div className="flex space-x-4 items-center">
                                <Textarea
                                    value={inputValue}
                                    onChange={(e) => setInputValue(e.target.value)}
                                    onKeyPress={handleKeyPress}
                                    placeholder={isCompareMode
                                        ? `对比 ${getModeLabel(compareMode1)} 和 ${getModeLabel(compareMode2)} 的回答...`
                                        : "Ask me anything about your knowledge base..."
                                    }
                                    className="flex-1 h-7 resize-none"
                                    disabled={isLoading}
                                />
                                <Button
                                    onClick={handleSubmit}
                                    disabled={!inputValue.trim() || isLoading}
                                    size="lg"
                                    className="px-6"
                                >
                                    {isLoading ? (
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                    ) : (
                                        <Send className="w-4 h-4" />
                                    )}
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default observer(HyperRAGHome)
