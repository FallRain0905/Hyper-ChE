import React, { useState, useEffect } from 'react'
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
  Typography
} from 'antd'
import {
  DeleteOutlined,
  DatabaseOutlined,
  CloudUploadOutlined,
  ReloadOutlined,
  ClearOutlined,
  InboxOutlined
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
  const [selectedDatabase, setSelectedDatabase] = useState('default')
  const [cleanDatabase, setCleanDatabase] = useState(true)
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])

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

        // 清空数据库后，需要刷新全局数据库列表
        try {
          // 动态导入全局用户状态
          const { storeGlobalUser } = await import('../../store/globalUser')
          await storeGlobalUser.loadDatabases()

          // 如果当前选择的数据库被清空了，清除选择
          if (storeGlobalUser.selectedDatabase === selectedDatabase) {
            storeGlobalUser.selectedDatabase = ''
            storeGlobalUser.lastSetDbValue = ''
            localStorage.removeItem('selectedDatabase')
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

    setUploadLoading(true)
    setUploadProgress(0)

    try {
      const formData = new FormData()
      fileList.forEach((file) => {
        if (file.originFileObj) {
          formData.append('files', file.originFileObj)
        }
      })

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
        body: formData
      })

      clearInterval(progressInterval)
      setUploadProgress(100)

      if (response.ok) {
        const data = await response.json()
        const successCount = data.files.filter((f: any) => f.status === 'uploaded').length
        const errorCount = data.files.filter((f: any) => f.status === 'error').length

        if (errorCount > 0) {
          message.warning(`上传完成：成功 ${successCount} 个，失败 ${errorCount} 个`)
        } else {
          message.success(`成功上传 ${successCount} 个文件`)
        }

        // 清空文件列表并关闭弹窗
        setFileList([])
        setUploadModalVisible(false)
        loadFiles()
      } else {
        message.error('文件上传失败')
      }
    } catch (error) {
      console.error('上传文件失败:', error)
      message.error('文件上传失败')
    } finally {
      setUploadLoading(false)
      setUploadProgress(0)
    }
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

      setFileList([...fileList, file])
      return false
    }
  }

  // 表格列定义
  const columns: ColumnsType<FileInfo> = [
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
      render: (status: string) => {
        const statusConfig: Record<string, { color: string; text: string }> = {
          'uploaded': { color: 'success', text: '已上传' },
          'embedded': { color: 'processing', text: '已嵌入' },
          'error': { color: 'error', text: '错误' }
        }
        const config = statusConfig[status] || { color: 'default', text: status }
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
  }, [selectedDatabase])

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
              >
                <Select.Option value="default">默认数据库</Select.Option>
                <Select.Option value="iron_">Iron 数据库</Select.Option>
              </Select>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => {
                  loadFiles()
                  loadDatabaseStatus()
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
    </div>
  )
}

export default Files