import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  message,
  Select,
  Upload,
  Modal,
  InputNumber,
  Drawer,
  Input,
  Radio,
  Dropdown,
  Progress,
} from 'antd'
import {
  CloudUploadOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { SERVER_URL } from '../../utils'
import type { UploadFile, UploadProps } from 'antd/es/upload/interface'

interface FileInfo {
  file_id: string
  filename: string
  file_path: string
  upload_time: string
  file_size: number
  status: string
  original_filename?: string
  file_type?: string
  database_name?: string
  kb_name?: string
  processed_time?: string
  error_message?: string
}

interface KBInfo {
  kb_id: string
  name: string
  description: string
  database_name: string
  rag_system: string
  domain: string
  chunk_size: number
  chunk_overlap: number
  created_at: string
  updated_at: string
  stats?: {
    file_count: number
    embedded_count: number
    error_count: number
    total_size: number
  }
}

interface DomainInfo {
  id: string
  name: string
  description: string
}

const Files: React.FC = () => {
  const navigate = useNavigate()

  // KB state
  const [kbs, setKbs] = useState<KBInfo[]>([])
  const [activeKB, setActiveKB] = useState<KBInfo | null>(null)
  const [kbLoading, setKbLoading] = useState(false)

  // KB creation modal
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [newKBName, setNewKBName] = useState('')
  const [newKBDesc, setNewKBDesc] = useState('')
  const [newKBRagSystem, setNewKBRagSystem] = useState('hyperrag')
  const [newKBDomain, setNewKBDomain] = useState('default')
  const [newKBChunkSize, setNewKBChunkSize] = useState(1000)
  const [newKBChunkOverlap, setNewKBChunkOverlap] = useState(200)
  const [creating, setCreating] = useState(false)
  const [domains, setDomains] = useState<DomainInfo[]>([])

  // File state (within KB)
  const [files, setFiles] = useState<FileInfo[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [cleanDatabase, setCleanDatabase] = useState(true)

  // Upload state
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [fileList, setFileList] = useState<UploadFile[]>([])

  // Embed state
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set())
  const [isEmbedding, setIsEmbedding] = useState(false)
  const [embeddingProgress, setEmbeddingProgress] = useState<{
    current: number
    total: number
    percentage: number
    message: string
  }>({} as any)
  const [progressDetails, setProgressDetails] = useState<Record<string, any>>({})
  const [logs, setLogs] = useState<any[]>([])
  const [logsVisible, setLogsVisible] = useState(false)

  // Tab state
  const [activeTab, setActiveTab] = useState<'docs' | 'settings'>('docs')

  const wsRef = useRef<WebSocket | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)

  // ============ KB Management ============

  const loadKBs = async () => {
    setKbLoading(true)
    try {
      const res = await fetch(`${SERVER_URL}/kb`)
      if (res.ok) {
        setKbs(await res.json())
      }
    } catch (e) {
      console.error('加载知识库失败:', e)
    } finally {
      setKbLoading(false)
    }
  }

  const loadDomains = async () => {
    try {
      const res = await fetch(`${SERVER_URL}/domains`)
      if (res.ok) {
        const data = await res.json()
        setDomains(Array.isArray(data) ? data : data.domains || [])
      }
    } catch (e) {
      console.error('加载领域列表失败:', e)
    }
  }

  const handleCreateKB = async () => {
    if (!newKBName.trim()) {
      message.warning('请输入知识库名称')
      return
    }
    setCreating(true)
    try {
      const res = await fetch(`${SERVER_URL}/kb`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newKBName.trim(),
          description: newKBDesc,
          rag_system: newKBRagSystem,
          domain: newKBDomain,
          chunk_size: newKBChunkSize,
          chunk_overlap: newKBChunkOverlap,
        }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        message.success('知识库创建成功')
        setCreateModalVisible(false)
        setNewKBName('')
        setNewKBDesc('')
        setNewKBRagSystem('hyperrag')
        setNewKBDomain('default')
        setNewKBChunkSize(1000)
        setNewKBChunkOverlap(200)
        loadKBs()
      } else {
        message.error(data.detail || '创建失败')
      }
    } catch (e) {
      message.error('创建知识库失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDeleteKB = async (kbName: string) => {
    Modal.confirm({
      title: '确认删除知识库',
      content: '将同时删除所有文件和数据库，此操作不可恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await fetch(`${SERVER_URL}/kb/${encodeURIComponent(kbName)}`, { method: 'DELETE' })
          const data = await res.json()
          if (data.success) {
            message.success('知识库已删除')
            if (activeKB?.database_name === kbName) setActiveKB(null)
            loadKBs()
          } else {
            message.error(data.detail || '删除失败')
          }
        } catch (e) {
          message.error('删除失败')
        }
      },
    })
  }

  // ============ File Management (within KB) ============

  const loadKBFiles = async (kbDbName: string) => {
    setFilesLoading(true)
    try {
      const res = await fetch(`${SERVER_URL}/files`)
      if (res.ok) {
        const data = await res.json()
        const kbFiles = (data.files || []).filter((f: FileInfo) => f.kb_name === kbDbName || f.database_name === kbDbName)
        setFiles(kbFiles)
      }
    } catch (e) {
      console.error('加载文件列表失败:', e)
    } finally {
      setFilesLoading(false)
    }
  }

  const enterKB = (kb: KBInfo) => {
    setActiveKB(kb)
    setSelectedFileIds(new Set())
    setActiveTab('docs')
    loadKBFiles(kb.database_name)
  }

  const exitKB = () => {
    setActiveKB(null)
    setFiles([])
    setSelectedFileIds(new Set())
    loadKBs()
  }

  // Upload
  const handleUpload = async () => {
    if (fileList.length === 0 || !activeKB) return
    setUploadLoading(true)
    setUploadProgress(0)
    try {
      const formData = new FormData()
      fileList.filter(f => f.originFileObj).forEach(f => {
        if (f.originFileObj) formData.append('files', f.originFileObj)
      })
      formData.append('kb_name', activeKB.database_name)

      const progressInterval = setInterval(() => {
        setUploadProgress(prev => prev >= 90 ? (clearInterval(progressInterval), 90) : prev + 10)
      }, 200)

      const res = await fetch(`${SERVER_URL}/files/upload`, { method: 'POST', body: formData })
      clearInterval(progressInterval)
      setUploadProgress(100)

      if (res.ok) {
        const data = await res.json()
        const successCount = data.files?.filter((f: any) => f.status === 'uploaded').length || 0
        message.success(`成功上传 ${successCount} 个文件`)
        setFileList([])
        setUploadModalVisible(false)
        loadKBFiles(activeKB.database_name)
      } else {
        message.error('上传失败')
      }
    } catch (e) {
      message.error('上传失败')
    } finally {
      setUploadLoading(false)
      setUploadProgress(0)
    }
  }

  // Embed
  const handleEmbed = async (fileIds?: string[]) => {
    const ids = fileIds || Array.from(selectedFileIds)
    if (ids.length === 0 || !activeKB) return
    setIsEmbedding(true)
    setEmbeddingProgress({} as any)
    setProgressDetails({})
    setLogs([])
    setLogsVisible(true)

    try {
      const res = await fetch(`${SERVER_URL}/files/embed-with-progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_ids: ids,
          kb_name: activeKB.database_name,
        }),
      })
      const data = await res.json()
      if (data.processing) {
        message.success(`开始处理 ${data.total_files} 个文档`)
      } else {
        setIsEmbedding(false)
        message.error('处理失败')
      }
    } catch (e) {
      setIsEmbedding(false)
      message.error('嵌入失败')
    }
  }

  const handleEmbedAll = () => {
    const unembedded = files.filter(f => f.status !== 'embedded').map(f => f.file_id)
    if (unembedded.length === 0) {
      message.info('所有文档已嵌入')
      return
    }
    handleEmbed(unembedded)
  }

  // File operations
  const deleteFile = async (fileId: string) => {
    try {
      const res = await fetch(`${SERVER_URL}/files/${fileId}?clean_database=true`, { method: 'DELETE' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '删除失败')
      }
      message.success('文件已删除')
      if (activeKB) loadKBFiles(activeKB.database_name)
    } catch (e: any) {
      message.error(e.message || '删除失败')
    }
  }

  const handleSelectAll = () => {
    if (selectedFileIds.size === files.length) {
      setSelectedFileIds(new Set())
    } else {
      setSelectedFileIds(new Set(files.map(f => f.file_id)))
    }
  }

  // Helpers
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  const getFileTypeInfo = (filename: string) => {
    const ext = filename?.split('.').pop()?.toLowerCase() || ''
    switch (ext) {
      case 'pdf': return { label: 'PDF', color: 'text-red-500', bg: 'bg-red-50' }
      case 'doc': case 'docx': return { label: 'DOC', color: 'text-blue-500', bg: 'bg-blue-50' }
      case 'md': return { label: 'MD', color: 'text-purple-500', bg: 'bg-purple-50' }
      case 'txt': return { label: 'TXT', color: 'text-gray-500', bg: 'bg-gray-50' }
      case 'csv': return { label: 'CSV', color: 'text-green-500', bg: 'bg-green-50' }
      default: return { label: ext.toUpperCase() || 'FILE', color: 'text-gray-500', bg: 'bg-gray-50' }
    }
  }

  // Upload props
  const uploadProps: UploadProps = {
    multiple: true,
    fileList,
    onRemove: (file) => {
      const idx = fileList.indexOf(file)
      const newList = fileList.slice()
      newList.splice(idx, 1)
      setFileList(newList)
    },
    beforeUpload: (file) => {
      const allowed = ['txt', 'md', 'pdf', 'doc', 'docx', 'csv']
      const ext = file.name.split('.').pop()?.toLowerCase()
      if (!allowed.includes(ext || '')) {
        message.error(`不支持的文件类型: ${file.name}`)
        return false
      }
      if (file.size / 1024 / 1024 > 50) {
        message.error('文件大小不能超过 50MB')
        return false
      }
      return false
    },
    onChange: (info) => setFileList(info.fileList),
  }

  // WebSocket
  useEffect(() => {
    connectWebSocket()
    return () => { wsRef.current?.close() }
  }, [])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const connectWebSocket = () => {
    try {
      const wsUrl = SERVER_URL.replace('http', 'ws') + '/ws'
      wsRef.current = new WebSocket(wsUrl)
      wsRef.current.onmessage = (event) => {
        try { handleProgressUpdate(JSON.parse(event.data)) } catch {}
      }
      wsRef.current.onclose = () => { setTimeout(connectWebSocket, 3000) }
    } catch {}
  }

  const handleProgressUpdate = (data: any) => {
    switch (data.type) {
      case 'progress':
        setEmbeddingProgress({ current: data.current || 0, total: data.total || 0, percentage: data.percentage || 0, message: data.message || '处理中...' })
        break
      case 'file_processing':
        setProgressDetails(prev => ({ ...prev, [data.file_id]: { filename: data.filename, stage: data.stage, message: data.message } }))
        break
      case 'file_completed':
        setProgressDetails(prev => { const u = { ...prev }; delete u[data.file_id]; return u })
        setFiles(prev => prev.map(f => f.file_id === data.file_id ? { ...f, status: 'embedded' } : f))
        break
      case 'file_error':
        setProgressDetails(prev => ({ ...prev, [data.file_id]: { error: data.error, message: `错误: ${data.error}` } }))
        setFiles(prev => prev.map(f => f.file_id === data.file_id ? { ...f, status: 'error' } : f))
        break
      case 'all_completed':
        setIsEmbedding(false)
        setEmbeddingProgress({} as any)
        setProgressDetails({})
        setSelectedFileIds(new Set())
        message.success('所有文档嵌入完成')
        if (activeKB) loadKBFiles(activeKB.database_name)
        break
      case 'error':
        setIsEmbedding(false)
        setEmbeddingProgress({} as any)
        setProgressDetails({})
        message.error(data.error || '嵌入出错')
        break
      case 'log':
        setLogs(prev => [...prev.slice(-49), { id: Date.now() + Math.random(), timestamp: new Date(data.timestamp * 1000).toLocaleTimeString(), level: data.level, message: data.message }])
        break
    }
  }

  useEffect(() => {
    loadKBs()
    loadDomains()
  }, [])

  // ============ RENDER ============

  // Level 2: KB Detail
  if (activeKB) {
    const embeddedCount = files.filter(f => f.status === 'embedded').length

    return (
      <div className="p-6">
        {/* Back link */}
        <button onClick={exitKB} className="text-sm text-gray-400 hover:text-gray-600 transition-colors mb-4 inline-block">
          ← 知识库
        </button>

        {/* KB Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{activeKB.name}</h1>
            {activeKB.description && <p className="text-sm text-gray-500 mt-1">{activeKB.description}</p>}
          </div>
          <div className="flex items-center gap-3">
            <span className="px-2.5 py-1 text-xs font-medium bg-blue-50 text-blue-600 rounded-full">
              {activeKB.rag_system === 'cograg' ? 'Cog-RAG' : 'HyperRAG'}
            </span>
            <span className="px-2.5 py-1 text-xs font-medium bg-gray-100 text-gray-500 rounded-full">
              {activeKB.domain}
            </span>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="flex border-b border-gray-200 mb-6">
          <button onClick={() => setActiveTab('docs')} className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === 'docs' ? 'border-gray-900 text-gray-900' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>
            文档 ({files.length})
          </button>
          <button onClick={() => setActiveTab('settings')} className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === 'settings' ? 'border-gray-900 text-gray-900' : 'border-transparent text-gray-400 hover:text-gray-600'}`}>
            设置
          </button>
        </div>

        {/* Docs Tab */}
        {activeTab === 'docs' && (
          <div>
            {/* Toolbar */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <p className="text-sm text-gray-500">{embeddedCount}/{files.length} 已嵌入</p>
                {files.length > 0 && (
                  <button onClick={handleSelectAll} className="text-xs text-blue-600 hover:text-blue-700">
                    {selectedFileIds.size === files.length ? '取消全选' : '全选'}
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                {files.some(f => f.status !== 'embedded') && (
                  <button onClick={handleEmbedAll} disabled={isEmbedding} className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors flex items-center gap-1.5">
                    <ThunderboltOutlined />
                    {isEmbedding ? '嵌入中...' : '嵌入全部'}
                  </button>
                )}
                {selectedFileIds.size > 0 && (
                  <button onClick={() => handleEmbed()} disabled={isEmbedding} className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors">
                    嵌入选中 ({selectedFileIds.size})
                  </button>
                )}
                <button onClick={() => setUploadModalVisible(true)} className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-1.5">
                  <CloudUploadOutlined />
                  上传文档
                </button>
              </div>
            </div>

            {/* Embedding Progress */}
            {isEmbedding && embeddingProgress.total > 0 && (
              <div className="bg-white border border-gray-200 rounded-xl p-4 mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-700">嵌入进度</span>
                  <span className="text-xs text-gray-500">{embeddingProgress.current}/{embeddingProgress.total}</span>
                </div>
                <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden mb-2">
                  <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${embeddingProgress.percentage || 0}%` }} />
                </div>
                <p className="text-xs text-gray-400">{embeddingProgress.message || '处理中...'}</p>
                {Object.keys(progressDetails).length > 0 && (
                  <div className="mt-2 space-y-1">
                    {Object.entries(progressDetails).map(([id, d]: [string, any]) => (
                      <div key={id} className="text-xs p-1.5 bg-gray-50 rounded">
                        <span className="font-medium text-gray-700">{d.filename}</span>
                        <span className="text-gray-400 ml-2">{d.message}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center justify-between mt-2">
                  <button onClick={() => setLogsVisible(true)} className="text-xs text-gray-400 hover:text-gray-600">查看日志 ({logs.length})</button>
                  <button onClick={() => { setIsEmbedding(false); setEmbeddingProgress({} as any); setProgressDetails({}); setLogs([]) }} className="text-xs text-red-400 hover:text-red-600">取消</button>
                </div>
              </div>
            )}

            {/* Files Grid */}
            {filesLoading ? (
              <div className="text-center py-12 text-gray-400">加载中...</div>
            ) : files.length === 0 ? (
              <div className="text-center py-16 bg-white border border-gray-100 rounded-xl">
                <p className="text-gray-400 mb-2">还没有文档</p>
                <button onClick={() => setUploadModalVisible(true)} className="text-blue-600 text-sm hover:text-blue-700">上传第一个文档</button>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {files.map((file) => {
                  const typeInfo = getFileTypeInfo(file.original_filename || file.filename)
                  const isSelected = selectedFileIds.has(file.file_id)
                  return (
                    <div
                      key={file.file_id}
                      className={`bg-white border rounded-xl p-4 hover:shadow-sm transition-all cursor-pointer flex flex-col group ${
                        isSelected ? 'border-blue-300 bg-blue-50/30' : 'border-gray-200 hover:border-gray-300'
                      }`}
                      onClick={() => setSelectedFileIds(prev => { const s = new Set(prev); if (s.has(file.file_id)) { s.delete(file.file_id) } else { s.add(file.file_id) }; return s })}
                    >
                      <div className="flex items-start gap-3 mb-3">
                        <div className={`w-10 h-10 rounded-lg ${typeInfo.bg} flex items-center justify-center text-xs font-medium ${typeInfo.color} uppercase shrink-0`}>
                          {typeInfo.label}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="font-medium text-gray-900 truncate text-sm" title={file.original_filename || file.filename}>
                            {file.original_filename || file.filename}
                          </h3>
                          <p className="text-xs text-gray-400 mt-0.5">{formatFileSize(file.file_size)}</p>
                        </div>
                        <Dropdown
                          menu={{
                            items: [
                              ...(file.status === 'embedded' ? [{ key: 'graph', label: '查看图谱', onClick: () => navigate('/Hyper/show') }] : []),
                              ...(file.status === 'embedded' ? [{ key: 'chat', label: '开始检索', onClick: async () => { const { storeGlobalUser } = await import('../../store/globalUser'); storeGlobalUser.setSelectedDatabase(file.database_name || ''); navigate('/Hyper/chat') } }] : []),
                              ...(file.status === 'uploaded' ? [{ key: 'embed', label: '嵌入此文档', onClick: () => handleEmbed([file.file_id]) }] : []),
                              { type: 'divider' as const },
                              { key: 'delete', label: '删除文件', danger: true, onClick: () => { Modal.confirm({ title: '删除文件', content: `确定要删除 "${file.filename}" 吗？`, okText: '确定', okType: 'danger', cancelText: '取消', onOk: () => deleteFile(file.file_id) }) } },
                            ],
                          }}
                          trigger={['click']}
                        >
                          <button onClick={(e) => e.stopPropagation()} className="p-1 text-gray-300 hover:text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity">
                            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" /></svg>
                          </button>
                        </Dropdown>
                      </div>
                      <div className="mt-auto pt-2 border-t border-gray-50 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className={`h-1 w-8 rounded-full ${file.status === 'embedded' ? 'bg-green-400' : file.status === 'error' ? 'bg-red-400' : progressDetails[file.file_id] ? 'bg-blue-400 animate-pulse' : 'bg-gray-200'}`} />
                          <span className={`text-xs ${file.status === 'embedded' ? 'text-green-600' : file.status === 'error' ? 'text-red-500' : progressDetails[file.file_id] ? 'text-blue-600' : 'text-gray-400'}`}>
                            {file.status === 'embedded' ? '已嵌入' : file.status === 'error' ? '错误' : progressDetails[file.file_id] ? '处理中' : '已上传'}
                          </span>
                        </div>
                        <span className="text-xs text-gray-300">{new Date(file.upload_time).toLocaleDateString('zh-CN')}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Settings Tab */}
        {activeTab === 'settings' && (
          <div className="space-y-4 max-w-lg">
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-medium text-gray-700 mb-4">知识库设置</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-gray-500 block mb-1">名称</label>
                  <div className="text-sm text-gray-900">{activeKB.name}</div>
                </div>
                <div>
                  <label className="text-xs text-gray-500 block mb-1">描述</label>
                  <div className="text-sm text-gray-700">{activeKB.description || '无'}</div>
                </div>
                <div>
                  <label className="text-xs text-gray-500 block mb-1">RAG 系统</label>
                  <div className="text-sm text-gray-900">{activeKB.rag_system === 'cograg' ? 'Cog-RAG' : 'HyperRAG'}</div>
                </div>
                <div>
                  <label className="text-xs text-gray-500 block mb-1">领域</label>
                  <div className="text-sm text-gray-900">{activeKB.domain}</div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">分块大小</label>
                    <div className="text-sm text-gray-900">{activeKB.chunk_size}</div>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">重叠大小</label>
                    <div className="text-sm text-gray-900">{activeKB.chunk_overlap}</div>
                  </div>
                </div>
              </div>
            </div>
            <button onClick={() => handleDeleteKB(activeKB.database_name)} className="px-4 py-2 text-sm text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors">
              删除知识库
            </button>
          </div>
        )}

        {/* Upload Modal */}
        <Modal
          title="上传文档"
          open={uploadModalVisible}
          onOk={handleUpload}
          onCancel={() => { setUploadModalVisible(false); setFileList([]); setUploadProgress(0) }}
          okText="开始上传"
          cancelText="取消"
          okButtonProps={{ loading: uploadLoading, disabled: fileList.length === 0 }}
          width={500}
        >
          <div className="space-y-4">
            <p className="text-sm text-gray-500">文档将上传到知识库「{activeKB.name}」</p>
            <Upload.Dragger {...uploadProps}>
              <p className="ant-upload-drag-icon"><CloudUploadOutlined style={{ fontSize: 40, color: '#2563eb' }} /></p>
              <p className="ant-upload-text">点击或拖拽文件到此区域</p>
              <p className="ant-upload-hint text-xs text-gray-400">支持 TXT, MD, PDF, DOC, DOCX, CSV</p>
            </Upload.Dragger>
            {uploadLoading && <Progress percent={uploadProgress} status={uploadProgress === 100 ? 'success' : 'active'} />}
            {fileList.length > 0 && !uploadLoading && <p className="text-sm text-gray-500">已选择 {fileList.length} 个文件</p>}
          </div>
        </Modal>

        {/* Log Drawer */}
        <Drawer title="嵌入日志" placement="right" width={500} open={logsVisible} onClose={() => setLogsVisible(false)}>
          <div ref={logsEndRef} className="bg-gray-900 text-gray-300 p-3 rounded-lg font-mono text-xs min-h-[300px] max-h-[calc(100vh-120px)] overflow-y-auto">
            {logs.length === 0 ? <div className="text-center text-gray-600 py-8">暂无日志</div> : logs.map(log => (
              <div key={log.id} className={`mb-1 ${log.level === 'ERROR' ? 'text-red-400' : log.level === 'WARNING' ? 'text-amber-400' : log.level === 'INFO' ? 'text-blue-400' : 'text-gray-400'}`}>
                <span className="text-gray-600 mr-2">{log.timestamp}</span>
                <span className="mr-2">[{log.level}]</span>
                {log.message}
              </div>
            ))}
          </div>
        </Drawer>
      </div>
    )
  }

  // Level 1: KB List
  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">知识库</h1>
          <p className="text-sm text-gray-500 mt-1">上传文档，AI 解析构建知识图谱</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadKBs} className="p-2 text-gray-400 hover:text-gray-600 transition-colors" title="刷新">
            <ReloadOutlined />
          </button>
          <button onClick={() => setCreateModalVisible(true)} className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-1.5">
            <PlusOutlined />
            新建知识库
          </button>
        </div>
      </div>

      {kbLoading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : kbs.length === 0 ? (
        <div className="text-center py-16 bg-white border border-gray-100 rounded-xl">
          <p className="text-gray-400 mb-2">还没有知识库</p>
          <button onClick={() => setCreateModalVisible(true)} className="text-blue-600 text-sm hover:text-blue-700">创建第一个</button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {kbs.map((kb) => (
            <div
              key={kb.kb_id}
              className="bg-white border border-gray-200 rounded-xl p-5 hover:border-gray-300 hover:shadow-sm transition-all cursor-pointer group"
              onClick={() => enterKB(kb)}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-gray-900 truncate group-hover:text-blue-600 transition-colors">{kb.name}</h3>
                  {kb.description && <p className="text-sm text-gray-500 mt-1 line-clamp-2">{kb.description}</p>}
                  <div className="flex items-center gap-2 mt-2">
                    <span className="px-2 py-0.5 text-xs bg-blue-50 text-blue-600 rounded-full">{kb.rag_system === 'cograg' ? 'Cog-RAG' : 'HyperRAG'}</span>
                    <span className="text-xs text-gray-400">{kb.stats?.file_count || 0} 个文档</span>
                    {kb.stats && kb.stats.embedded_count > 0 && (
                      <span className="text-xs text-green-500">{kb.stats.embedded_count} 已嵌入</span>
                    )}
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDeleteKB(kb.database_name) }}
                  className="text-gray-300 hover:text-red-500 transition-colors ml-2 shrink-0"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create KB Modal */}
      <Modal
        title="新建知识库"
        open={createModalVisible}
        onOk={handleCreateKB}
        onCancel={() => setCreateModalVisible(false)}
        okText="创建"
        cancelText="取消"
        okButtonProps={{ loading: creating, disabled: !newKBName.trim() }}
        width={500}
      >
        <div className="space-y-4">
          <div>
            <label className="text-sm text-gray-700 block mb-1">名称 *</label>
            <Input value={newKBName} onChange={(e) => setNewKBName(e.target.value)} placeholder="输入知识库名称" />
          </div>
          <div>
            <label className="text-sm text-gray-700 block mb-1">描述</label>
            <Input value={newKBDesc} onChange={(e) => setNewKBDesc(e.target.value)} placeholder="描述（可选）" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-gray-700 block mb-1">RAG 系统</label>
              <Select value={newKBRagSystem} onChange={setNewKBRagSystem} style={{ width: '100%' }}>
                <Select.Option value="hyperrag">HyperRAG</Select.Option>
                <Select.Option value="cograg">Cog-RAG</Select.Option>
              </Select>
            </div>
            <div>
              <label className="text-sm text-gray-700 block mb-1">领域</label>
              <Select value={newKBDomain} onChange={setNewKBDomain} style={{ width: '100%' }}>
                {domains.map(d => (
                  <Select.Option key={d.id || d.name} value={d.id || d.name}>{d.name}</Select.Option>
                ))}
                {domains.length === 0 && <Select.Option value="default">default</Select.Option>}
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm text-gray-700 block mb-1">分块大小</label>
              <InputNumber value={newKBChunkSize} onChange={(v) => setNewKBChunkSize(v || 1000)} min={100} max={5000} step={100} style={{ width: '100%' }} />
            </div>
            <div>
              <label className="text-sm text-gray-700 block mb-1">重叠大小</label>
              <InputNumber value={newKBChunkOverlap} onChange={(v) => setNewKBChunkOverlap(v || 0)} min={0} max={1000} step={50} style={{ width: '100%' }} />
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default Files
