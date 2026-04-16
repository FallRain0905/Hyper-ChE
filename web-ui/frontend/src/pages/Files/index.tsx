import React, { useState, useEffect, useRef } from 'react'
import {
  Card,
  Table,
  Button,
  message,
  Space,
  Tag,
  Popconfirm,
  Statistic,
  Row,
  Col,
  Alert,
  Tooltip,
  Select,
  Upload,
  Modal,
  Progress,
  Typography,
  Checkbox,
  InputNumber,
  Drawer
} from 'antd'
import {
  DeleteOutlined,
  DatabaseOutlined,
  CloudUploadOutlined,
  ReloadOutlined,
  ClearOutlined,
  InboxOutlined,
  ThunderboltOutlined
} from '@ant-design/icons'
import { SERVER_URL } from '../../utils'
import type { ColumnsType } from 'antd/es/table'
import type { UploadFile, UploadProps } from 'antd/es/upload/interface'

const { Dragger } = Upload
const { Text } = Typography

interface FileInfo {
  file_id: string
  filename: string
  file_path: string
  upload_time: string
  file_size: number
  status: string
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

  // 嵌入功能相关状态
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
  const [progressDetails, setProgressDetails] = useState<Record<string, any>>({})
  const [logs, setLogs] = useState<any[]>([])
  const [showLogs, setShowLogs] = useState(false)
  const [logsVisible, setLogsVisible] = useState(false)
  const [availableDatabases, setAvailableDatabases] = useState<DatabaseInfo[]>([])

  interface DatabaseInfo {
    name: string
    description: string
  }

  const wsRef = useRef<WebSocket | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)

  // 加载文件列表
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

  // 加载数据库状态
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

  // 加载数据库列表
  const loadDatabases = async () => {
    try {
      const { storeGlobalUser } = await import('../../store/globalUser')
      await storeGlobalUser.loadDatabases()
      console.log('数据库列表已更新:', storeGlobalUser.availableDatabases)

      // 同时更新本地的数据库列表状态
      setAvailableDatabases(storeGlobalUser.availableDatabases)
    } catch (error) {
      console.error('加载数据库列表失败:', error)
    }
  }

  // 数据库删除处理函数
  const handleDeleteDatabase = async (databaseName: string) => {
    Modal.confirm({
      title: '确认删除数据库',
      content: `确定要删除数据库 "${databaseName}" 吗？此操作将永久删除HyperRAG和Cog-RAG中的所有相关数据，无法恢复。`,
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

            // 如果删除的是当前选中的数据库，清除选择
            if (selectedDatabase === databaseName) {
              setSelectedDatabase('');
            }

            // WebSocket会自动刷新列表，但手动刷新作为备份
            await loadDatabases();

            // 清空文件列表（因为这些文件关联的数据库已被删除）
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

  // WebSocket连接和进度处理
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
      console.log('连接WebSocket:', wsUrl)

      wsRef.current = new WebSocket(wsUrl)

      wsRef.current.onopen = () => {
        console.log('WebSocket连接已建立')
      }

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          console.log('WebSocket消息:', data)
          handleProgressUpdate(data)
        } catch (error) {
          console.error('解析WebSocket消息失败:', error)
        }
      }

      wsRef.current.onclose = () => {
        console.log('WebSocket连接已关闭')
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
        // 更新文件列表中的状态
        setFiles(prev => prev.map(file =>
          file.file_id === data.file_id
            ? { ...file, status: 'embedded' }
            : file
        ))
        // 文件嵌入完成后，刷新数据库列表
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

  // 删除文件
  const deleteFile = async (fileId: string) => {
    setDeleteLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/files/${fileId}?clean_database=${cleanDatabase}`, {
        method: 'DELETE'
      })

      if (response.ok) {
        const data = await response.json()
        message.success(data.message || '文件删除成功')
        loadFiles() // 重新加载文件列表
        loadDatabaseStatus() // 更新数据库状态
      } else {
        const error = await response.json()
        message.error(error.detail || '文件删除失败')
      }
    } catch (error) {
      console.error('删除文件失败:', error)
      message.error('删除文件失败')
    } finally {
      setDeleteLoading(false)
    }
  }

  // 清空数据库
  const clearDatabase = async () => {
    setClearLoading(true)
    try {
      const response = await fetch(`${SERVER_URL}/database/clear?database=${selectedDatabase}`, {
        method: 'POST'
      })

      if (response.ok) {
        const data = await response.json()
        message.success(data.message || '数据库已清空')

        // 清空数据库后，需要刷新数据库列表
        try {
          // 动态导入全局用户状态
          const { storeGlobalUser } = await import('../../store/globalUser')
          await storeGlobalUser.loadDatabases()

          // 刷新本地数据库列表
          await loadDatabases()

          // 如果当前选择的数据库被清空了，清除选择
          if (storeGlobalUser.selectedDatabase === selectedDatabase) {
            storeGlobalUser.selectedDatabase = ''
            storeGlobalUser.lastSetDbValue = ''
            localStorage.removeItem('selectedDatabase')
            setSelectedDatabase('') // 同时更新本地状态
          }
        } catch (error) {
          console.error('刷新数据库列表失败:', error)
        }

        loadDatabaseStatus() // 更新数据库状态
        loadFiles() // 重新加载文件列表
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

  // 格式化文件大小
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) {
      return '0 B'
    }
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  // 处理文件上传
  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.warning('请选择要上传的文件')
      return
    }

    console.log('开始上传，fileList:', fileList)
    console.log('fileList详情:', fileList.map(f => ({
      name: f.name,
      hasOriginFileObj: !!f.originFileObj,
      originFileObjType: f.originFileObj?.constructor.name,
      fileSize: f.originFileObj?.size
    })))

    setUploadLoading(true)
    setUploadProgress(0)

    try {
      const formData = new FormData()

      // 确保每个文件都有originFileObj
      const validFiles = fileList.filter(file => file.originFileObj)

      console.log('有效的文件:', validFiles.map(f => f.name))

      if (validFiles.length === 0) {
        message.error('没有有效的文件可以上传，请重新选择文件')
        setUploadLoading(false)
        return
      }

      validFiles.forEach((file) => {
        if (file.originFileObj) {
          formData.append('files', file.originFileObj)
          console.log('添加文件到FormData:', file.name, '大小:', file.originFileObj.size)
        }
      })

      console.log('FormData构建完成，包含文件数:', formData.getAll('files').length)

      // 模拟上传进度
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
        // 不设置Content-Type，让浏览器自动设置multipart/form-data边界
      })

      clearInterval(progressInterval)
      setUploadProgress(100)

      console.log('上传响应状态:', response.status, response.statusText)

      if (response.ok) {
        const data = await response.json()
        console.log('上传响应数据:', data)

        const successCount = data.files?.filter((f: any) => f.status === 'uploaded').length || 0
        const errorCount = data.files?.filter((f: any) => f.status === 'error').length || 0

        if (errorCount > 0) {
          // 显示具体错误信息
          const errorFiles = data.files?.filter((f: any) => f.status === 'error')
          const errorDetails = errorFiles?.map((f: any) => `${f.filename}: ${f.error}`).join('\n') || ''
          message.warning(`上传完成：成功 ${successCount} 个，失败 ${errorCount} 个${errorDetails ? '\n' + errorDetails : ''}`)
        } else {
          message.success(`成功上传 ${successCount} 个文件`)
        }

        // 清空文件列表并关闭弹窗
        setFileList([])
        setUploadModalVisible(false)
        loadFiles()
      } else {
        const errorText = await response.text()
        console.error('上传失败响应:', errorText)
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

  // 处理文档嵌入
  const handleEmbedDocuments = async () => {
    if (selectedFileIds.size === 0) {
      message.warning('请先选择要嵌入的文档')
      return
    }

    setIsEmbedding(true)
    setEmbeddingProgress({} as any)
    setProgressDetails({})
    setLogs([])
    setLogsVisible(true)

    try {
      const response = await fetch(`${SERVER_URL}/files/embed-with-progress`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file_ids: Array.from(selectedFileIds),
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          rag_system: selectedRAGSystem
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

  // 处理文件选择
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

  // 上传组件配置
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
      console.log('beforeUpload 被调用, file:', file.name, 'size:', file.size, 'type:', file.type)

      // 检查文件类型
      const allowedExtensions = ['txt', 'md', 'pdf', 'doc', 'docx', 'csv']
      const fileExtension = file.name.split('.').pop()?.toLowerCase()

      if (!allowedExtensions.includes(fileExtension || '')) {
        message.error(`不支持的文件类型: ${file.name}`)
        return false
      }

      // 检查文件大小 (限制为50MB)
      const isLt50M = file.size / 1024 / 1024 < 50
      if (!isLt50M) {
        message.error('文件大小不能超过 50MB')
        return false
      }

      // 返回false阻止自动上传，文件会被添加到fileList中
      return false
    },
    onChange: (info) => {
      console.log('Upload onChange:', info)
      console.log('当前fileList:', info.fileList)
      // 更新fileList状态
      setFileList(info.fileList)
    },
    // 移除customRequest，让Upload组件正常处理文件
  }

  // 表格列定义
  const columns: ColumnsType<FileInfo> = [
    {
      title: '选择',
      key: 'selection',
      width: 60,
      render: (_: any, record: FileInfo) => (
        <Checkbox
          checked={selectedFileIds.has(record.file_id)}
          onChange={(e) => handleFileSelection(record.file_id, e.target.checked)}
          disabled={isEmbedding}
        />
      )
    },
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      render: (filename: string) => (
        <Tooltip title={filename}>
          <span>{filename}</span>
        </Tooltip>
      )
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size: number) => formatFileSize(size)
    },
    {
      title: '上传时间',
      dataIndex: 'upload_time',
      key: 'upload_time',
      width: 180,
      render: (time: string) => new Date(time).toLocaleString('zh-CN')
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string, record: FileInfo) => {
        const statusConfig: Record<string, { color: string; text: string }> = {
          'uploaded': { color: 'default', text: '已上传' },
          'embedded': { color: 'success', text: '已嵌入' },
          'error': { color: 'error', text: '错误' }
        }
        const config = statusConfig[status] || { color: 'default', text: status }

        // 如果正在嵌入，显示处理状态
        if (progressDetails[record.file_id]) {
          return (
            <Space direction="vertical" size="small">
              <Tag color="processing">处理中</Tag>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                {progressDetails[record.file_id].message}
              </Text>
            </Space>
          )
        }

        return <Tag color={config.color}>{config.text}</Tag>
      }
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: FileInfo) => (
        <Space>
          <Popconfirm
            title="删除文件"
            description={
              <div>
                <p>确定要删除文件 &quot;{record.filename}&quot; 吗？</p>
                <div style={{ marginTop: 8 }}>
                  <label>
                    <input
                      type="checkbox"
                      checked={cleanDatabase}
                      onChange={(e) => setCleanDatabase(e.target.checked)}
                      style={{ marginRight: 4 }}
                    />
                    同时清理数据库中的嵌入数据
                  </label>
                </div>
              </div>
            }
            onConfirm={() => deleteFile(record.file_id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="text"
              danger
              size="small"
              icon={<DeleteOutlined />}
              loading={deleteLoading}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ]

  useEffect(() => {
    loadFiles()
    loadDatabaseStatus()
    // 加载数据库列表
    loadDatabases()
  }, [])

  // 当数据库列表更新时，如果当前没有选择数据库，自动选择第一个
  useEffect(() => {
    if (!selectedDatabase && availableDatabases.length > 0) {
      setSelectedDatabase(availableDatabases[0].name)
    }
  }, [availableDatabases])

  // 当数据库列表更新时，如果当前选择的数据库不存在了，清除选择
  useEffect(() => {
    if (selectedDatabase && availableDatabases.length > 0) {
      const exists = availableDatabases.find(db => db.name === selectedDatabase)
      if (!exists) {
        setSelectedDatabase('')
      }
    }
  }, [availableDatabases, selectedDatabase])

  return (
    <div className="m-2">
      <Card>
        <div className="mb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center text-2xl font-bold">
              <DatabaseOutlined style={{ marginRight: '8px' }} />
              文件管理
            </div>
            <Space>
              <Button
                type="primary"
                icon={<CloudUploadOutlined />}
                onClick={() => setUploadModalVisible(true)}
              >
                上传文档
              </Button>
              <Select
                value={selectedDatabase}
                onChange={setSelectedDatabase}
                style={{ width: 200 }}
                placeholder="选择数据库"
                loading={availableDatabases.length === 0}
              >
                {availableDatabases.map((db) => (
                  <Select.Option key={db.name} value={db.name}>
                    {db.description}
                  </Select.Option>
                ))}
              </Select>
              {selectedDatabase && (
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleDeleteDatabase(selectedDatabase)}
                >
                  删除数据库
                </Button>
              )}
              <Button
                icon={<ReloadOutlined />}
                onClick={() => {
                  loadFiles()
                  loadDatabaseStatus()
                  loadDatabases() // 添加数据库列表刷新
                }}
              >
                刷新
              </Button>
            </Space>
          </div>
        </div>

        {/* 数据库状态信息 */}
        {dbStatus && (
          <Card
            size="small"
            style={{ marginBottom: 16 }}
            title={
              <span>
                <DatabaseOutlined style={{ marginRight: 8 }} />
                数据库状态: {selectedDatabase}
              </span>
            }
            extra={
              <Popconfirm
                title="清空数据库"
                description={
                  <Alert
                    message="危险操作"
                    description="这将清空数据库中的所有数据，包括所有文档的嵌入数据、实体关系等。此操作不可恢复！"
                    type="error"
                    showIcon
                    style={{ marginTop: 8 }}
                  />
                }
                onConfirm={clearDatabase}
                okText="确定清空"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  danger
                  size="small"
                  icon={<ClearOutlined />}
                  loading={clearLoading}
                >
                  清空数据库
                </Button>
              </Popconfirm>
            }
          >
            <Row gutter={16}>
              <Col span={6}>
                <Statistic
                  title="状态"
                  value={dbStatus.exists ? '存在' : '不存在'}
                  valueStyle={{ color: dbStatus.exists ? '#3f8600' : '#cf1322' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="内存实例"
                  value={dbStatus.has_instance ? '已加载' : '未加载'}
                  valueStyle={{ color: dbStatus.has_instance ? '#3f8600' : '#faad14' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="占用空间"
                  value={dbStatus.size_mb}
                  suffix="MB"
                  precision={2}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="文件数量"
                  value={files.length}
                  suffix="个"
                />
              </Col>
            </Row>
          </Card>
        )}

        {/* 重要提示 */}
        <Alert
          message="重要提示"
          description={
            <div>
              <p>• 删除文件时，建议勾选&quot;同时清理数据库中的嵌入数据&quot;以保持数据一致性</p>
              <p>• 清空数据库将删除所有嵌入数据，需要重新嵌入文档</p>
              <p>• 切换嵌入模型维度时，必须清空数据库并重新嵌入</p>
            </div>
          }
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />

        {/* 嵌入功能面板 */}
        <Card
          size="small"
          style={{ marginBottom: 16 }}
          title={
            <span>
              <ThunderboltOutlined style={{ marginRight: 8 }} />
              文档嵌入
            </span>
          }
        >
          <Row gutter={16} align="middle">
            <Col span={6}>
              <div>
                <Text strong>RAG系统:</Text>
                <Select
                  value={selectedRAGSystem}
                  onChange={setSelectedRAGSystem}
                  style={{ width: '100%', marginTop: 4 }}
                  disabled={isEmbedding}
                >
                  <Select.Option value="hyperrag">HyperRAG</Select.Option>
                  <Select.Option value="cograg">Cog-RAG</Select.Option>
                </Select>
              </div>
            </Col>
            <Col span={6}>
              <div>
                <Text strong>分块大小:</Text>
                <InputNumber
                  value={chunkSize}
                  onChange={setChunkSize}
                  min={100}
                  max={5000}
                  step={100}
                  style={{ width: '100%', marginTop: 4 }}
                  disabled={isEmbedding}
                />
              </div>
            </Col>
            <Col span={6}>
              <div>
                <Text strong>重叠大小:</Text>
                <InputNumber
                  value={chunkOverlap}
                  onChange={setChunkOverlap}
                  min={0}
                  max={1000}
                  step={50}
                  style={{ width: '100%', marginTop: 4 }}
                  disabled={isEmbedding}
                />
              </div>
            </Col>
            <Col span={6}>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={handleEmbedDocuments}
                disabled={selectedFileIds.size === 0 || isEmbedding}
                loading={isEmbedding}
                block
              >
                {isEmbedding ? '嵌入中...' : `嵌入文档 (${selectedFileIds.size})`}
              </Button>
            </Col>
          </Row>

          {/* 嵌入进度显示 */}
          {isEmbedding && embeddingProgress.total > 0 && (
            <div style={{ marginTop: 16 }}>
              <Row gutter={16}>
                <Col span={18}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <Text strong>嵌入进度:</Text>
                      <Text>{embeddingProgress.current || 0}/{embeddingProgress.total}</Text>
                    </div>
                    <Progress
                      percent={embeddingProgress.percentage || 0}
                      status={embeddingProgress.percentage === 100 ? 'success' : 'active'}
                    />
                    <Text type="secondary" style={{ fontSize: '12px' }}>
                      {embeddingProgress.message || '处理中...'}
                    </Text>
                  </div>
                </Col>
                <Col span={6}>
                  <Button
                    danger
                    onClick={() => {
                      setIsEmbedding(false)
                      setEmbeddingProgress({} as any)
                      setProgressDetails({})
                      setLogs([])
                    }}
                    block
                  >
                    取消嵌入
                  </Button>
                </Col>
              </Row>

              {/* 处理中的文件详情 */}
              {Object.keys(progressDetails).length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text strong>处理中的文件:</Text>
                  <div style={{ marginTop: 8, maxHeight: 150, overflowY: 'auto' }}>
                    {Object.entries(progressDetails).map(([fileId, details]: [string, any]) => (
                      <div key={fileId} style={{ padding: '8px', borderBottom: '1px solid #f0f0f0' }}>
                        <Text strong>{details.filename}</Text>
                        <br />
                        <Text type="secondary" style={{ fontSize: '12px' }}>
                          {details.message}
                        </Text>
                        {details.error && (
                          <Text type="danger" style={{ fontSize: '12px', display: 'block' }}>
                            {details.error}
                          </Text>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 日志显示按钮 */}
              <div style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  onClick={() => setLogsVisible(true)}
                  icon={<DatabaseOutlined />}
                >
                  查看详细日志 ({logs.length})
                </Button>
              </div>
            </div>
          )}
        </Card>

        {/* 文件列表 */}
        <Table
          columns={columns}
          dataSource={files}
          rowKey="file_id"
          loading={loading}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个文件`
          }}
        />
      </Card>

      {/* 上传文件弹窗 */}
      <Modal
        title="上传文档"
        open={uploadModalVisible}
        onOk={handleUpload}
        onCancel={() => {
          setUploadModalVisible(false)
          setFileList([])
          setUploadProgress(0)
        }}
        okText="开始上传"
        cancelText="取消"
        okButtonProps={{
          loading: uploadLoading,
          disabled: fileList.length === 0
        }}
        width={600}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Text strong>支持文件类型：</Text>
            <Text type="secondary">TXT, MD, PDF, DOC, DOCX, CSV</Text>
          </div>

          <div>
            <Text strong>文件大小限制：</Text>
            <Text type="secondary">单个文件最大 50MB</Text>
          </div>

          <Dragger {...uploadProps} style={{ padding: '20px' }}>
            <p className="ant-upload-drag-icon">
              <InboxOutlined style={{ fontSize: 48, color: '#1890ff' }} />
            </p>
            <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
            <p className="ant-upload-hint">
              支持单个或批量上传。严禁上传公司数据或其他敏感文件。
            </p>
          </Dragger>

          {uploadLoading && (
            <div>
              <Text strong>上传进度：</Text>
              <Progress percent={uploadProgress} status={uploadProgress === 100 ? 'success' : 'active'} />
            </div>
          )}

          {fileList.length > 0 && !uploadLoading && (
            <Alert
              message={`已选择 ${fileList.length} 个文件`}
              description={fileList.map(f => f.name).join(', ')}
              type="info"
              showIcon
            />
          )}
        </Space>
      </Modal>

      {/* 日志面板 */}
      <Drawer
        title={
          <span>
            <DatabaseOutlined style={{ marginRight: 8 }} />
            嵌入处理日志
          </span>
        }
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
            borderRadius: '4px',
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