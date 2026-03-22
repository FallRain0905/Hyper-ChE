import React, { useEffect, useRef } from 'react';
import { Select, Typography, Space, Button, message, Spin } from 'antd';
import type { SizeType } from 'antd/es/config-provider/SizeContext';
import { observer } from 'mobx-react';
import { DatabaseOutlined, ReloadOutlined } from '@ant-design/icons';
import { storeGlobalUser } from '../../store/globalUser';
import { useTranslation } from 'react-i18next';

const { Text } = Typography;
const { Option } = Select;

interface DatabaseSelectorProps {
  /** 显示模式：选择器/按钮组/紧凑模式 */
  mode?: 'select' | 'buttons' | 'compact';
  /** 是否显示刷新按钮 */
  showRefresh?: boolean;
  /** 选择器占位文本 */
  placeholder?: string;
  /** 自定义样式 */
  style?: React.CSSProperties;
  /** 组件大小 */
  size?: SizeType;
  /** 数据库变更回调 */
  onChange?: (value: string) => void;
  /** 是否禁用 */
  disabled?: boolean;
}

/**
 * 数据库选择组件
 */
const DatabaseSelector: React.FC<DatabaseSelectorProps> = ({
    mode = 'select',
    showRefresh = false,
    placeholder,
    style = {},
    size = 'middle',
    onChange,
    disabled = false
}) => {
  const { t } = useTranslation();

  // 使用 ref 确保只在组件首次挂载时恢复数据库
  const hasRestoredRef = useRef(false);

  // 初始化数据库列表（只在首次挂载时）
  useEffect(() => {
    if (!hasRestoredRef.current) {
      hasRestoredRef.current = true;

      console.log('[DatabaseSelector] 首次挂载，开始初始化');
      console.log('[DatabaseSelector] 当前 selectedDatabase:', storeGlobalUser.selectedDatabase);
      console.log('[DatabaseSelector] 当前 availableDatabases 数量:', storeGlobalUser.availableDatabases.length);

      if (!storeGlobalUser.selectedDatabase) {
        storeGlobalUser.restoreSelectedDatabase();
      }

      if (storeGlobalUser.availableDatabases.length === 0) {
        storeGlobalUser.loadDatabases();
      }
    }
  }, []);

  // 处理数据库变更
  const handleDatabaseChange = (value: string) => {
    console.log('[DatabaseSelector] handleDatabaseChange 被调用, value:', value);
    storeGlobalUser.setSelectedDatabase(value);
    onChange?.(value);
  };

  // 刷新数据库列表
  const handleRefresh = async () => {
    try {
      await storeGlobalUser.loadDatabases();
      message.success(t('database.refresh_success'));
    } catch (error) {
      message.error(t('database.refresh_failed'));
    }
  };

  // 选择器模式
  const renderSelectMode = () => (
    <Space size="middle" style={style}>
      <Select
        value={storeGlobalUser.selectedDatabase}
        onChange={handleDatabaseChange}
        style={{ minWidth: 250 }}
        placeholder={placeholder}
        size={size}
        disabled={disabled}
        loading={storeGlobalUser.availableDatabases.length === 0}
        popupRender={(menu) => (
          <div>
            {menu}
            {showRefresh && (
              <div style={{ padding: '8px', borderTop: '1px solid #f0f0f0' }}>
                <Button
                  type="text"
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={handleRefresh}
                  style={{ width: '100%' }}
                >
                  刷新列表
                </Button>
              </div>
            )}
          </div>
        )}
      >
        {storeGlobalUser.availableDatabases.map((db) => (
          <Option key={db.name} value={db.name}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <DatabaseOutlined style={{ marginRight: 6, color: '#1890ff' }} />
                {db.description}
              </div>
            </div>
          </Option>
        ))}
      </Select>
      {showRefresh && (
        <Button
          type="text"
          size={size}
          icon={<ReloadOutlined />}
          onClick={handleRefresh}
          disabled={disabled}
        />
      )}
    </Space>
  );

  // 按钮组模式
  const renderButtonsMode = () => (
    <Space size="small" style={style}>
      {storeGlobalUser.availableDatabases.map((db) => (
        <Button
          key={db.name}
          size={size}
          type={storeGlobalUser.selectedDatabase === db.name ? 'primary' : 'default'}
          onClick={() => handleDatabaseChange(db.name)}
          disabled={disabled}
          icon={<DatabaseOutlined />}
          title={db.description}
          style={{
            borderColor: storeGlobalUser.selectedDatabase === db.name ? '#1890ff' : undefined,
            borderRadius: '0.5rem'
          }}
          className='py-5 px-3'
        >
          {db.description.replace('超图', '')}
        </Button>
      ))}
      {showRefresh && (
        <Button
          type="text"
          size={size}
          icon={<ReloadOutlined />}
          onClick={handleRefresh}
          disabled={disabled}
        />
      )}
    </Space>
  );

  // 紧凑模式
  const renderCompactMode = () => (
    <Space size="small" style={style}>
      <Select
        value={storeGlobalUser.selectedDatabase}
        onChange={handleDatabaseChange}
        style={{ minWidth: 180 }}
        size={size}
        disabled={disabled}
        placeholder={placeholder}
      >
        {storeGlobalUser.availableDatabases.map((db) => (
          <Option key={db.name} value={db.name} title={db.description}>
            <DatabaseOutlined style={{ marginRight: 6, color: '#1890ff' }} />
            {db.description}
          </Option>
        ))}
      </Select>
    </Space>
  );

  // 加载状态
  if (storeGlobalUser.availableDatabases.length === 0) {
    return (
      <Space style={style}>
        <Spin size="small" />
        <Text type="secondary">加载数据库列表...</Text>
      </Space>
    );
  }

  // 根据模式渲染不同的UI
  switch (mode) {
    case 'buttons':
      return renderButtonsMode();
    case 'compact':
      return renderCompactMode();
    case 'select':
    default:
      return renderSelectMode();
  }
};

export default observer(DatabaseSelector);
