import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  message,
  Select,
  Upload,
  Modal,
  Progress,
  InputNumber,
  Drawer,
  Input,
  Radio,
  Dropdown
} from 'antd'
import {
  DatabaseOutlined,
  CloudUploadOutlined,
  ReloadOutlined,
  ClearOutlined,
  InboxOutlined,
  ThunderboltOutlined,
  PlusOutlined,
  FileTextOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileMarkdownOutlined,
  DeleteOutlined
} from '@ant-design/icons'
import { SERVER_URL } from '../../utils'
import type { UploadFile, UploadProps } from 'antd/es/upload/interface'

const { Dragger } = Upload
const { Group: RadioGroup } = Radio

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
  processed_time?: string
  error_message?: string
}

interface DatabaseInfo {
  name: string
  description: string
}

interface DatabaseStatus {
  database: string
  exists: boolean
  has_instance: boolean
  size_bytes: number
  size_mb: number
  path: string
}

const Files: React.FC = () => {
  const navigate = useNavigate()
  const [files, setFiles] = useState<FileInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const [clearLoading, setClearLoading] = useState(false)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [dbStatus, setDbStatus] = useState<DatabaseStatus | null>(null)
  const [selectedDatabase, setSelectedDatabase] = useState('')
  const [cleanDatabase, setCleanDatabase] = useState(true)
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])

  // upload database selection
  const [uploadDatabaseMode, setUploadDatabaseMode] = useState<'auto' | 'existing' | 'new'>('auto')
  const [uploadTargetDatabase, setUploadTargetDatabase] = useState<string>('')
  const [uploadNewDatabaseName, setUploadNewDatabaseName] = useState<string>('')

  // embed states
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set())
  const [isEmbedding, setIsEmbedding] = useState(false)
  const [selectedRAGSystem, setSelectedRAGSystem] = useState('hyperrag')
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [embeddingProgress, setEmbeddingProgress] = useState<{
    current: number
    total: number
    percentage: number
    message: string
  }>({} as any)

  // embed database selection
  const [embedDatabaseMode, setEmbedDatabaseMode] = useState<'file' | 'existing' | 'new'>('file')
  const [targetDatabase, setTargetDatabase] = useState<string>('')
  const [newDatabaseName, setNewDatabaseName] = useState<string>('')
  const [progressDetails, setProgressDetails] = useState<Record<string, any>>({})
  const [logs, setLogs] = useState<any[]>([])
  const [logsVisible, setLogsVisible] = useState(false)
  const [availableDatabases, setAvailableDatabases] = useState<DatabaseInfo[]>([])

  // tab state
  const [activeTab, setActiveTab] = useState<'files' | 'embed'>('files')

  const wsRef = useRef<WebSocket | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)

  // load files
  const loadFiles = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/files`)
      if (response.ok) {
        const data = await response.json()
        setFiles(data.files || [])
      } else {
        message.error('获取文件列表失败')
      }
    } catch (error) {
      console.error('获取文件列表失败:', error)
      message.error('获取文件列表失败')
    } finally {
      setLoading(false)
    }
  }

  // load database status
  const loadDatabaseStatus = async () => {
    if (!selectedDatabase) {
      setDbStatus(null)
      return
    }
    try {
      const response = await fetch(`${SERVER_URL}/database/status?database=${selectedDatabase}`)
      if (response.ok) {
        const data = await response.json()
        setDbStatus(data)
      }
    } catch (error) {
      console.error('获取数据库状态失败:', error)
    }
  }

  // load databases
  const loadDatabases = async () => {
    try {
      const { storeGlobalUser } = await import('../../store/globalUser')
      await storeGlobalUser.loadDatabases()
      setAvailableDatabases(storeGlobalUser.availableDatabases)
    } catch (error) {
      console.error('加载数据库列表失败:', error)
    }
  }

  // delete database
  const handleDeleteDatabase = async (databaseName: string) => {
    Modal.confirm({
      title: '确认删除数据库',
      content: `确定要删除数据库 "${databaseName}" 吗？此操作将永久删除所有相关数据，无法恢复。`,
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const response = await fetch(`${SERVER_URL}/databases/${encodeURIComponent(databaseName)}`, {
            method: 'DELETE',
          });
          const result = await response.json();
          if (result.success) {
            message.success(`数据库 "${databaseName}" 删除成功`);
            if (selectedDatabase === databaseName) {
              setSelectedDatabase('');
            }
            await loadDatabases();
            setFiles([]);
          } else {
            message.error(`删除失败: ${result.message}`);
          }
        } catch (error) {
          console.error('删除数据库失败:', error);
          message.error('删除数据库失败，请重试');
        }
      },
    });
  };

  // WebSocket
  useEffect(() => {
    connectWebSocket()
    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  const connectWebSocket = () => {
    try {
      const wsUrl = SERVER_URL.replace('http', 'ws') + '/ws'
      wsRef.current = new WebSocket(wsUrl)

      wsRef.current.onopen = () => {
        console.log('WebSocket连接已建立')
      }

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          handleProgressUpdate(data)
        } catch (error) {
          console.error('解析WebSocket消息失败:', error)
        }
      }

      wsRef.current.onclose = () => {
        setTimeout(connectWebSocket, 3000)
      }

      wsRef.current.onerror = (error) => {
        console.error('WebSocket错误:', error)
      }
    } catch (error) {
      console.error('WebSocket连接失败:', error)
    }
  }

  const handleProgressUpdate = (data: any) => {
    switch (data.type) {
      case 'progress':
        setEmbeddingProgress({
          current: data.current || 0,
          total: data.total || 0,
          percentage: data.percentage || 0,
          message: data.message || '处理中...'
        })
        break
      case 'file_processing':
        setProgressDetails(prev => ({
          ...prev,
          [data.file_id]: {
            filename: data.filename,
            stage: data.stage,
            message: data.message
          }
        }))
        break
      case 'file_completed':
        setProgressDetails(prev => {
          const updated = { ...prev }
          delete updated[data.file_id]
          return updated
        })
        setFiles(prev => prev.map(file =>
          file.file_id === data.file_id
            ? { ...file, status: 'embedded' }
            : file
        ))
        loadDatabases()
        break
      case 'file_error':
        setProgressDetails(prev => ({
          ...prev,
          [data.file_id]: {
            error: data.error,
            message: `错误: ${data.error}`
          }
        }))
        setFiles(prev => prev.map(file =>
          file.file_id === data.file_id
            ? { ...file, status: 'error' }
            : file
        ))
        break
      case 'all_completed':
        setIsEmbedding(false)
        setEmbeddingProgress({} as any)
        setProgressDetails({})
        setSelectedFileIds(new Set())
        message.success('所有文档嵌入完成')
        loadFiles()
        break
      case 'error':
        setIsEmbedding(false)
        setEmbeddingProgress({} as any)
        setProgressDetails({})
        message.error(data.error || '嵌入过程出错')
        break
      case 'log': {
        const logEntry = {
          id: Date.now() + Math.random(),
          timestamp: new Date(data.timestamp * 1000).toLocaleTimeString(),
          level: data.level,
          message: data.message
        }
        setLogs(prev => [...prev.slice(-49), logEntry])
        break
      }
      default:
        break
    }
  }

  // delete file
  const deleteFile = async (fileId: string) => {
    setDeleteLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/files/${fileId}?clean_database=${cleanDatabase}`, {
        method: 'DELETE'
      })
      if (response.ok) {
        const data = await response.json()
        message.success(data.message || '文件删除成功')
        loadFiles()
        loadDatabaseStatus()
      } else {
        const error = await response.json()
        message.error(error.detail || '文件删除失败')
      }
    } catch (error) {
      console.error('删除文件失败:', error)
      message.error('文件删除失败')
    } finally {
      setDeleteLoading(false)
    }
  }

  // clear database
  const clearDatabase = async () => {
    setClearLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/database/clear?database=${selectedDatabase}`, {
        method: 'POST'
      })
      if (response.ok) {
        message.success('数据库已清空')
        try {
          const { storeGlobalUser } = await import('../../store/globalUser')
          await storeGlobalUser.loadDatabases()
          await loadDatabases()
          if (storeGlobalUser.selectedDatabase === selectedDatabase) {
            storeGlobalUser.setSelectedDatabase('')
            setSelectedDatabase('')
          }
        } catch (error) {
          console.error('刷新数据库列表失败:', error)
        }
        loadDatabaseStatus()
        loadFiles()
      } else {
        const error = await response.json()
        message.error(error.detail || '清空数据库失败')
      }
    } catch (error) {
      console.error('清空数据库失败:', error)
      message.error('清空数据库失败')
    } finally {
      setClearLoading(false)
    }
  }

  // format file size
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  // handle upload
  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.warning('请选择要上传的文件')
      return
    }

    let finalTargetDatabase: string | null = null
    if (uploadDatabaseMode === 'existing') {
      if (!uploadTargetDatabase) {
        message.warning('请选择目标数据库')
        return
      }
      finalTargetDatabase = uploadTargetDatabase
    } else if (uploadDatabaseMode === 'new') {
      if (!uploadNewDatabaseName.trim()) {
        message.warning('请输入新数据库名称')
        return
      }
      finalTargetDatabase = uploadNewDatabaseName.trim()
    }

    setUploadLoading(true)
    setUploadProgress(0)

    try {
      const formData = new FormData()
      const validFiles = fileList.filter(file => file.originFileObj)

      if (validFiles.length === 0) {
        message.error('没有有效的文件可以上传')
        setUploadLoading(false)
        return
      }

      validFiles.forEach((file) => {
        if (file.originFileObj) {
          formData.append('files', file.originFileObj)
        }
      })

      if (finalTargetDatabase) {
        formData.append('target_database', finalTargetDatabase)
      }

      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval)
            return 90
          }
          return prev + 10
        })
      }, 200)

      const response = await fetch(`${SERVER_URL}/files/upload`, {
        method: 'POST',
        body: formData,
      })

      clearInterval(progressInterval)
      setUploadProgress(100)

      if (response.ok) {
        const data = await response.json()
        const successCount = data.files?.filter((f: any) => f.status === 'uploaded').length || 0
        const errorCount = data.files?.filter((f: any) => f.status === 'error').length || 0

        if (errorCount > 0) {
          const errorFiles = data.files?.filter((f: any) => f.status === 'error')
          const errorDetails = errorFiles?.map((f: any) => `${f.filename}: ${f.error}`).join('\n') || ''
          message.warning(`上传完成：成功 ${successCount} 个，失败 ${errorCount} 个${errorDetails ? '\n' + errorDetails : ''}`)
        } else {
          message.success(`成功上传 ${successCount} 个文件`)
        }

        setFileList([])
        setUploadModalVisible(false)
        loadFiles()
      } else {
        const errorText = await response.text()
        try {
          const errorData = JSON.parse(errorText)
          message.error(`文件上传失败: ${errorData.detail || errorData.message || '未知错误'}`)
        } catch {
          message.error(`文件上传失败: ${response.status} ${response.statusText}`)
        }
      }
    } catch (error) {
      console.error('上传文件失败:', error)
      message.error('文件上传失败: ' + (error as Error).message)
    } finally {
      setUploadLoading(false)
      setUploadProgress(0)
    }
  }

  // handle embed
  const handleEmbedDocuments = async () => {
    if (selectedFileIds.size === 0) {
      message.warning('请先选择要嵌入的文档')
      return
    }

    let finalTargetDatabase: string | null = null
    if (embedDatabaseMode === 'existing') {
      if (!targetDatabase) {
        message.warning('请选择目标数据库')
        return
      }
      finalTargetDatabase = targetDatabase
    } else if (embedDatabaseMode === 'new') {
      if (!newDatabaseName.trim()) {
        message.warning('请输入新数据库名称')
        return
      }
      finalTargetDatabase = newDatabaseName.trim()
    }

    setIsEmbedding(true)
    setEmbeddingProgress({} as any)
    setProgressDetails({})
    setLogs([])
    setLogsVisible(true)

    try {
      const response = await fetch(`${SERVER_URL}/files/embed-with-progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_ids: Array.from(selectedFileIds),
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          rag_system: selectedRAGSystem,
          target_database: finalTargetDatabase,
          update_file_database: embedDatabaseMode !== 'file'
        }),
      })

      const data = await response.json()

      if (data.processing) {
        message.success(`开始处理 ${data.total_files} 个文档`)
      } else {
        setIsEmbedding(false)
        message.error('处理失败')
      }
    } catch (error) {
      setIsEmbedding(false)
      message.error('文档嵌入失败')
    }
  }

  // file selection
  const handleFileSelection = (fileId: string, checked: boolean) => {
    setSelectedFileIds(prev => {
      const newSet = new Set(prev)
      if (checked) {
        newSet.add(fileId)
      } else {
        newSet.delete(fileId)
      }
      return newSet
    })
  }

  // select all
  const handleSelectAll = () => {
    if (selectedFileIds.size === files.length) {
      setSelectedFileIds(new Set())
    } else {
      setSelectedFileIds(new Set(files.map(f => f.file_id)))
    }
  }

  // upload props
  const uploadProps: UploadProps = {
    multiple: true,
    fileList,
    onRemove: (file) => {
      const index = fileList.indexOf(file)
      const newFileList = fileList.slice()
      newFileList.splice(index, 1)
      setFileList(newFileList)
    },
    beforeUpload: (file) => {
      const allowedExtensions = ['txt', 'md', 'pdf', 'doc', 'docx', 'csv']
      const fileExtension = file.name.split('.').pop()?.toLowerCase()

      if (!allowedExtensions.includes(fileExtension || '')) {
        message.error(`不支持的文件类型: ${file.name}`)
        return false
      }

      const isLt50M = file.size / 1024 / 1024 < 50
      if (!isLt50M) {
        message.error('文件大小不能超过 50MB')
        return false
      }

      return false
    },
    onChange: (info) => {
      setFileList(info.fileList)
    },
  }

  // get file type icon and label
  const getFileTypeInfo = (filename: string) => {
    const ext = filename?.split('.').pop()?.toLowerCase() || ''
    switch (ext) {
      case 'pdf':
        return { label: 'PDF', color: 'text-red-500', bg: 'bg-red-50' }
      case 'doc':
      case 'docx':
        return { label: 'DOC', color: 'text-blue-500', bg: 'bg-blue-50' }
      case 'md':
        return { label: 'MD', color: 'text-purple-500', bg: 'bg-purple-50' }
      case 'txt':
        return { label: 'TXT', color: 'text-gray-500', bg: 'bg-gray-50' }
      case 'csv':
        return { label: 'CSV', color: 'text-green-500', bg: 'bg-green-50' }
      default:
        return { label: ext.toUpperCase() || 'FILE', color: 'text-gray-500', bg: 'bg-gray-50' }
    }
  }

  // status config
  const getStatusInfo = (status: string, fileId: string) => {
    if (progressDetails[fileId]) {
      return { label: '处理中', className: 'text-blue-600', dot: 'bg-blue-500' }
    }
    switch (status) {
      case 'embedded':
        return { label: '已嵌入', className: 'text-green-600', dot: 'bg-green-500' }
      case 'error':
        return { label: '错误', className: 'text-red-500', dot: 'bg-red-500' }
      default:
        return { label: '已上传', className: 'text-gray-400', dot: 'bg-gray-300' }
    }
  }

  useEffect(() => {
    loadFiles()
    loadDatabaseStatus()
    loadDatabases()
  }, [])

  useEffect(() => {
    if (!selectedDatabase && availableDatabases.length > 0) {
      setSelectedDatabase(availableDatabases[0].name)
    }
  }, [availableDatabases])

  useEffect(() => {
    if (selectedDatabase && availableDatabases.length > 0) {
      const exists = availableDatabases.find(db => db.name === selectedDatabase)
      if (!exists) {
        setSelectedDatabase('')
      }
    }
  }, [availableDatabases, selectedDatabase])

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const tabs = [
    { key: 'files' as const, label: '文档' },
    { key: 'embed' as const, label: '嵌入配置' },
  ]

  return (
    <div className="px-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">文件管理</h1>
          <p className="text-sm text-gray-500 mt-1">上传文档，AI 解析构建知识图谱</p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={selectedDatabase}
            onChange={setSelectedDatabase}
            style={{ width: 200 }}
            placeholder="选择数据库"
            loading={availableDatabases.length === 0}
            size="middle"
          >
            {availableDatabases.map((db) => (
              <Select.Option key={db.name} value={db.name}>
                {db.description}
              </Select.Option>
            ))}
          </Select>
          <button
            onClick={() => {
              loadFiles()
              loadDatabaseStatus()
              loadDatabases()
            }}
            className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
            title="刷新"
          >
            <ReloadOutlined />
          </button>
        </div>
      </div>

      {/* Database Status Card */}
      {dbStatus && (
        <div className="bg-white border border-gray-100 rounded-xl p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
              <DatabaseOutlined className="text-blue-500" />
              数据库: {selectedDatabase}
            </h3>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  Modal.confirm({
                    title: '确认清空数据库',
                    content: '这将清空数据库中的所有数据，包括所有文档的嵌入数据、实体关系等。此操作不可恢复！',
                    okText: '确定清空',
                    okType: 'danger',
                    cancelText: '取消',
                    onOk: clearDatabase,
                  });
                }}
                disabled={clearLoading}
                className="px-3 py-1.5 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 transition-colors"
              >
                {clearLoading ? '清空中...' : '清空'}
              </button>
              <button
                onClick={() => handleDeleteDatabase(selectedDatabase)}
                disabled={deleteLoading}
                className="px-3 py-1.5 text-xs text-red-500 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50 transition-colors"
              >
                删除数据库
              </button>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className={`text-lg font-bold ${dbStatus.exists ? 'text-green-600' : 'text-red-500'}`}>
                {dbStatus.exists ? '存在' : '不存在'}
              </div>
              <div className="text-xs text-gray-500">状态</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className={`text-lg font-bold ${dbStatus.has_instance ? 'text-green-600' : 'text-amber-500'}`}>
                {dbStatus.has_instance ? '已加载' : '未加载'}
              </div>
              <div className="text-xs text-gray-500">内存实例</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-lg font-bold text-gray-900">{dbStatus.size_mb?.toFixed(2)}</div>
              <div className="text-xs text-gray-500">MB 占用</div>
            </div>
            <div className="text-center p-3 bg-gray-50 rounded-lg">
              <div className="text-lg font-bold text-gray-900">{files.length}</div>
              <div className="text-xs text-gray-500">个文件</div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Bar */}
      <div className="flex border-b border-gray-200 mb-6">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-gray-900 text-gray-900'
                : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Files Tab */}
      {activeTab === 'files' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <p className="text-sm text-gray-500">{files.length} 个文档</p>
              {files.length > 0 && (
                    <button
                    onClick={handleSelectAll}
                    className="text-xs text-blue-600 hover:text-blue-700 transition-colors"
                  >
                    {selectedFileIds.size === files.length ? '取消全选' : '全选'}
                  </button>
                )}
              {selectedFileIds.size > 0 && (
                <span className="text-xs text-gray-400">
                  已选 {selectedFileIds.size} 个
                </span>
              )}
            </div>
            <div className="flex gap-2">
              {selectedFileIds.size > 0 && (
                <button
                  onClick={handleEmbedDocuments}
                  disabled={isEmbedding}
                  className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                >
                  <ThunderboltOutlined />
                  {isEmbedding ? '嵌入中...' : `嵌入 (${selectedFileIds.size})`}
                </button>
              )}
              <button
                onClick={() => setUploadModalVisible(true)}
                className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-800 transition-colors flex items-center gap-1.5"
              >
                <CloudUploadOutlined />
                上传文档
              </button>
            </div>
          </div>

          {/* Embedding Progress */}
          {isEmbedding && embeddingProgress.total > 0 && (
            <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">嵌入进度</span>
                <span className="text-xs text-gray-500">
                  {embeddingProgress.current || 0}/{embeddingProgress.total}
                </span>
              </div>
              <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden mb-2">
                <div
                  className="h-full bg-green-500 rounded-full transition-all"
                  style={{ width: `${embeddingProgress.percentage || 0}%` }}
                />
              </div>
              <p className="text-xs text-gray-400">{embeddingProgress.message || '处理中...'}</p>

              {Object.keys(progressDetails).length > 0 && (
                <div className="mt-3 space-y-2">
                  {Object.entries(progressDetails).map(([fileId, details]: [string, any]) => (
                    <div key={fileId} className="text-xs p-2 bg-gray-50 rounded-lg">
                      <span className="font-medium text-gray-700">{details.filename}</span>
                      <span className="text-gray-400 ml-2">{details.message}</span>
                      {details.error && (
                        <span className="text-red-500 ml-2">{details.error}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center justify-between mt-3">
                <button
                  onClick={() => setLogsVisible(true)}
                  className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  查看日志 ({logs.length})
                </button>
                <button
                  onClick={() => {
                    setIsEmbedding(false)
                    setEmbeddingProgress({} as any)
                    setProgressDetails({})
                    setLogs([])
                  }}
                  className="text-xs text-red-400 hover:text-red-600 transition-colors"
                >
                  取消嵌入
                </button>
              </div>
            </div>
          )}

          {loading ? (
            <div className="text-center py-12 text-gray-400">加载中...</div>
          ) : files.length === 0 ? (
            <div className="text-center py-16 bg-white border border-gray-100 rounded-xl">
              <p className="text-gray-400 mb-2">还没有文档</p>
              <p className="text-xs text-gray-300 mb-4">支持 TXT, MD, PDF, DOC, DOCX, CSV 格式</p>
              <button
                onClick={() => setUploadModalVisible(true)}
                className="text-blue-600 text-sm hover:text-blue-700 transition-colors"
              >
                上传第一个文档
              </button>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {files.map((file) => {
                const typeInfo = getFileTypeInfo(file.original_filename || file.filename)
                const statusInfo = getStatusInfo(file.status, file.file_id)
                const isSelected = selectedFileIds.has(file.file_id)

                return (
                  <div
                    key={file.file_id}
                    className={`bg-white border rounded-xl p-4 hover:shadow-sm transition-all cursor-pointer flex flex-col group ${
                      isSelected ? 'border-blue-300 bg-blue-50/30' : 'border-gray-200 hover:border-gray-300'
                    }`}
                    onClick={() => handleFileSelection(file.file_id, !isSelected)}
                  >
                    {/* Header: type badge + filename + actions */}
                    <div className="flex items-start gap-3 mb-3">
                      <div className={`w-10 h-10 rounded-lg ${typeInfo.bg} flex items-center justify-center text-xs font-medium ${typeInfo.color} uppercase shrink-0`}>
                        {typeInfo.label}
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="font-medium text-gray-900 truncate text-sm" title={file.original_filename || file.filename}>
                          {file.original_filename || file.filename}
                        </h3>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {formatFileSize(file.file_size)}
                          {file.database_name && (
                            <>
                              {' · '}
                              <span className="text-blue-500">{file.database_name}</span>
                            </>
                          )}
                        </p>
                      </div>
                      {/* ... menu */}
                      <Dropdown
                        menu={{
                          items: [
                            ...(file.database_name ? [{
                              key: 'graph',
                              label: '查看图谱',
                              onClick: () => navigate(`/Hyper/show`),
                            }] : []),
                            ...(file.database_name ? [{
                              key: 'chat',
                              label: '开始检索',
                              onClick: async () => {
                                const { storeGlobalUser } = await import('../../store/globalUser')
                                storeGlobalUser.setSelectedDatabase(file.database_name || '')
                                navigate('/Hyper/chat')
                              },
                            }] : []),
                            { type: 'divider' as const },
                            {
                              key: 'delete',
                              label: '删除文件',
                              danger: true,
                              onClick: () => {
                                Modal.confirm({
                                  title: '删除文件',
                                  content: (
                                    <div>
                                      <p>确定要删除文件 &quot;{file.filename}&quot; 吗？</p>
                                      <div style={{ marginTop: 8 }}>
                                        <label className="flex items-center gap-1.5 text-sm text-gray-500">
                                          <input
                                            type="checkbox"
                                            checked={cleanDatabase}
                                            onChange={(e) => setCleanDatabase(e.target.checked)}
                                          />
                                          同时清理数据库中的嵌入数据
                                        </label>
                                      </div>
                                    </div>
                                  ),
                                  onOk: () => deleteFile(file.file_id),
                                  okText: '确定',
                                  cancelText: '取消',
                                });
                              },
                            },
                          ],
                        }}
                        trigger={['click']}
                      >
                        <button
                          onClick={(e) => e.stopPropagation()}
                          className="p-1 text-gray-300 hover:text-gray-500 transition-colors opacity-0 group-hover:opacity-100"
                        >
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                          </svg>
                        </button>
                      </Dropdown>
                    </div>

                    {/* Status bar */}
                    <div className="mt-auto pt-2 border-t border-gray-50">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {/* Status indicator: thin bar */}
                          <div className={`h-1 w-8 rounded-full ${
                            file.status === 'embedded' ? 'bg-green-400' :
                            file.status === 'error' ? 'bg-red-400' :
                            progressDetails[file.file_id] ? 'bg-blue-400 animate-pulse' :
                            'bg-gray-200'
                          }`} />
                          <span className={`text-xs ${
                            file.status === 'embedded' ? 'text-green-600' :
                            file.status === 'error' ? 'text-red-500' :
                            progressDetails[file.file_id] ? 'text-blue-600' :
                            'text-gray-400'
                          }`}>
                            {statusInfo.label}
                          </span>
                        </div>
                        <span className="text-xs text-gray-300">
                          {new Date(file.upload_time).toLocaleDateString('zh-CN')}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Embed Tab */}
      {activeTab === 'embed' && (
        <div className="space-y-4">
          {/* Target Database */}
          <div className="bg-white border border-gray-100 rounded-xl p-5">
            <h3 className="text-sm font-medium text-gray-700 mb-3">目标数据库</h3>
            <RadioGroup
              value={embedDatabaseMode}
              onChange={(e) => setEmbedDatabaseMode(e.target.value)}
              disabled={isEmbedding}
            >
              <Radio value="file">使用文件关联数据库</Radio>
              <Radio value="existing">嵌入到已有数据库</Radio>
              <Radio value="new">创建新数据库</Radio>
            </RadioGroup>

            {embedDatabaseMode === 'existing' && (
              <div className="mt-3">
                <Select
                  value={targetDatabase}
                  onChange={setTargetDatabase}
                  style={{ width: '100%' }}
                  placeholder="选择目标数据库"
                  disabled={isEmbedding}
                >
                  {availableDatabases.map((db) => (
                    <Select.Option key={db.name} value={db.name}>
                      {db.description || db.name}
                    </Select.Option>
                  ))}
                </Select>
              </div>
            )}

            {embedDatabaseMode === 'new' && (
              <div className="mt-3">
                <Input
                  value={newDatabaseName}
                  onChange={(e) => setNewDatabaseName(e.target.value)}
                  placeholder="输入新数据库名称"
                  disabled={isEmbedding}
                  prefix={<PlusOutlined />}
                />
              </div>
            )}
          </div>

          {/* Parameters */}
          <div className="bg-white border border-gray-100 rounded-xl p-5">
            <h3 className="text-sm font-medium text-gray-700 mb-3">嵌入参数</h3>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-gray-500 block mb-1">RAG 系统</label>
                <Select
                  value={selectedRAGSystem}
                  onChange={setSelectedRAGSystem}
                  style={{ width: '100%' }}
                  disabled={isEmbedding}
                >
                  <Select.Option value="hyperrag">HyperRAG</Select.Option>
                  <Select.Option value="cograg">Cog-RAG</Select.Option>
                </Select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">分块大小</label>
                <InputNumber
                  value={chunkSize}
                  onChange={(v) => setChunkSize(v || 1000)}
                  min={100}
                  max={5000}
                  step={100}
                  style={{ width: '100%' }}
                  disabled={isEmbedding}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">重叠大小</label>
                <InputNumber
                  value={chunkOverlap}
                  onChange={(v) => setChunkOverlap(v || 0)}
                  min={0}
                  max={1000}
                  step={50}
                  style={{ width: '100%' }}
                  disabled={isEmbedding}
                />
              </div>
            </div>
          </div>

          {/* Embedding Progress in Embed Tab */}
          {isEmbedding && embeddingProgress.total > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-gray-300">嵌入进度</h3>
                {isEmbedding && (
                  <span className="text-xs text-amber-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-pulse" />
                    文档嵌入需要调用 AI 模型，请耐心等待
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 mb-3">
                <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-500 rounded-full transition-all"
                    style={{ width: `${embeddingProgress.percentage || 0}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400">
                  {embeddingProgress.percentage?.toFixed(1) || 0}%
                </span>
              </div>
              <p className="text-xs text-gray-400 mb-2">
                {embeddingProgress.current || 0}/{embeddingProgress.total} — {embeddingProgress.message || '处理中...'}
              </p>

              {Object.keys(progressDetails).length > 0 && (
                <div className="space-y-1 mt-2">
                  {Object.entries(progressDetails).map(([fileId, details]: [string, any]) => (
                    <div key={fileId} className={`text-xs ${
                      details.error ? 'text-red-400' : 'text-gray-400'
                    }`}>
                      {details.filename}: {details.message}
                      {details.error && ` — ${details.error}`}
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center justify-between mt-3">
                <button
                  onClick={() => setLogsVisible(true)}
                  className="text-xs text-gray-400 hover:text-gray-300 transition-colors"
                >
                  查看完整日志 ({logs.length})
                </button>
                <button
                  onClick={() => {
                    setIsEmbedding(false)
                    setEmbeddingProgress({} as any)
                    setProgressDetails({})
                    setLogs([])
                  }}
                  className="text-xs text-red-400 hover:text-red-300 transition-colors"
                >
                  取消嵌入
                </button>
              </div>
            </div>
          )}

          {/* Action */}
          <button
            onClick={handleEmbedDocuments}
            disabled={selectedFileIds.size === 0 || isEmbedding}
            className="w-full px-4 py-2.5 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-800 disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
          >
            <ThunderboltOutlined />
            {isEmbedding ? '嵌入中...' : `嵌入选中文档 (${selectedFileIds.size})`}
          </button>

          {selectedFileIds.size === 0 && (
            <p className="text-xs text-gray-400 text-center">
              请先在「文档」标签页中选择要嵌入的文件
            </p>
          )}
        </div>
      )}

      {/* Upload Modal */}
      <Modal
        title="上传文档"
        open={uploadModalVisible}
        onOk={handleUpload}
        onCancel={() => {
          setUploadModalVisible(false)
          setFileList([])
          setUploadProgress(0)
          setUploadDatabaseMode('auto')
          setUploadTargetDatabase('')
          setUploadNewDatabaseName('')
        }}
        okText="开始上传"
        cancelText="取消"
        okButtonProps={{
          loading: uploadLoading,
          disabled: fileList.length === 0
        }}
        width={600}
      >
        <div className="space-y-4">
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-500">支持格式：</span>
            <span className="text-gray-400">TXT, MD, PDF, DOC, DOCX, CSV</span>
            <span className="text-gray-400">·</span>
            <span className="text-gray-400">单文件最大 50MB</span>
          </div>

          {/* Database Selection */}
          <div>
            <label className="text-sm font-medium text-gray-700 block mb-2">目标数据库</label>
            <RadioGroup
              value={uploadDatabaseMode}
              onChange={(e) => setUploadDatabaseMode(e.target.value)}
              disabled={uploadLoading}
            >
              <Radio value="auto">自动（文件名）</Radio>
              <Radio value="existing">已有数据库</Radio>
              <Radio value="new">新建数据库</Radio>
            </RadioGroup>
          </div>

          {uploadDatabaseMode === 'existing' && (
            <Select
              value={uploadTargetDatabase}
              onChange={setUploadTargetDatabase}
              style={{ width: '100%' }}
              placeholder="选择目标数据库"
              disabled={uploadLoading}
            >
              {availableDatabases.map((db) => (
                <Select.Option key={db.name} value={db.name}>
                  {db.description || db.name}
                </Select.Option>
              ))}
            </Select>
          )}

          {uploadDatabaseMode === 'new' && (
            <Input
              value={uploadNewDatabaseName}
              onChange={(e) => setUploadNewDatabaseName(e.target.value)}
              placeholder="输入新数据库名称"
              disabled={uploadLoading}
              prefix={<PlusOutlined />}
            />
          )}

          <Dragger {...uploadProps} style={{ padding: '20px' }}>
            <p className="ant-upload-drag-icon">
              <InboxOutlined style={{ fontSize: 48, color: '#1890ff' }} />
            </p>
            <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
            <p className="ant-upload-hint">
              支持单个或批量上传
            </p>
          </Dragger>

          {uploadLoading && (
            <div>
              <span className="text-sm text-gray-500">上传进度：</span>
              <Progress percent={uploadProgress} status={uploadProgress === 100 ? 'success' : 'active'} />
            </div>
          )}

          {fileList.length > 0 && !uploadLoading && (
            <div className="text-sm text-gray-500">
              已选择 {fileList.length} 个文件：{fileList.map(f => f.name).join(', ')}
            </div>
          )}
        </div>
      </Modal>

      {/* Log Drawer */}
      <Drawer
        title="嵌入处理日志"
        placement="right"
        width={600}
        open={logsVisible}
        onClose={() => setLogsVisible(false)}
      >
        <div
          ref={logsEndRef}
          style={{
            backgroundColor: '#1e1e1e',
            color: '#d4d4d4',
            padding: '12px',
            borderRadius: '8px',
            fontFamily: 'monospace',
            fontSize: '12px',
            minHeight: '400px',
            maxHeight: 'calc(100vh - 100px)',
            overflowY: 'auto'
          }}
        >
          {logs.length === 0 ? (
            <div style={{ color: '#888', textAlign: 'center', padding: '20px' }}>
              暂无日志记录
            </div>
          ) : (
            logs.map((log) => (
              <div
                key={log.id}
                style={{
                  marginBottom: '4px',
                  color: log.level === 'ERROR' ? '#f48771' :
                         log.level === 'WARNING' ? '#cca700' :
                         log.level === 'INFO' ? '#75beff' :
                         '#d4d4d4'
                }}
              >
                <span style={{ color: '#888', marginRight: '8px' }}>
                  {log.timestamp}
                </span>
                <span style={{ color: log.level === 'ERROR' ? '#f48771' :
                              log.level === 'WARNING' ? '#cca700' :
                              log.level === 'INFO' ? '#4ec9b0' :
                              '#569cd6', marginRight: '8px' }}>
                  [{log.level}]
                </span>
                {log.message}
              </div>
            ))
          )}
        </div>
      </Drawer>
    </div>
  )
}

export default Files