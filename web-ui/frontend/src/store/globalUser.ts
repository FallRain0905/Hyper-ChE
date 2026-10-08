import { makeAutoObservable } from 'mobx'
import { SERVER_URL } from '../utils'
import { authStore } from './auth'

class GlobalUser {
  userInfo: Partial<User.UserEntity> = {}
  selectedDatabase: string = ''
  availableDatabases: Array<{ name: string; description: string }> = []
  private isLoadingDatabases: boolean = false
  private lastSetDbValue: string = ''

  // 新增：可视化控制状态
  hasUserInitiatedVisualization: boolean = false  // 用户是否已点击开始可视化
  visualizationReady: boolean = false             // 可视化是否准备就绪

  constructor() {
    makeAutoObservable(this)
  }

  private selectedDatabaseKey() {
    const scope = authStore.user?.id || authStore.user?.email || 'anonymous'
    return `selectedDatabase_${scope}`
  }

  async getUserDetail() {
    // Identity now comes from the authenticated session; the legacy hard-coded
    // admin stub and its remote avatar URL have been removed.
    const user = authStore.user
    this.userInfo = user
      ? {
          username: user.display_name || user.email,
          roles: [{ id: user.role === 'admin' ? 5 : 1, name: user.role === 'admin' ? '管理员' : '用户', description: '', adminCount: 0, status: 1, sort: 1 }],
        }
      : {}
  }

  setUserInfo(user: Partial<User.UserEntity>) {
    this.userInfo = user
  }

  // 设置当前选中的数据库
  setSelectedDatabase(database: string) {
    // 防止重复设置相同值
    if (this.lastSetDbValue === database) {
      return;
    }
    this.lastSetDbValue = database;
    this.selectedDatabase = database
    // 保存到localStorage
    localStorage.setItem(this.selectedDatabaseKey(), database)
  }

  // 设置可用数据库列表
  setAvailableDatabases(databases: Array<{ name: string; description: string }>) {
    this.availableDatabases = databases

    // 检查当前选择的数据库是否还在列表中
    if (this.selectedDatabase && !databases.find(db => db.name === this.selectedDatabase)) {
      this.selectedDatabase = '';
      this.lastSetDbValue = '';
      localStorage.removeItem(this.selectedDatabaseKey());
    }

    // 注意：不再自动修改 selectedDatabase，让用户自己选择
    // 避免循环：不主动调用 setSelectedDatabase，只更新 availableDatabases 状态
  }

  // 从localStorage恢复选中的数据库（仅恢复名称，不触发加载）
  restoreSelectedDatabase() {
    const saved = localStorage.getItem(this.selectedDatabaseKey())
    if (saved && !this.selectedDatabase) {
      // 只在没有选中数据库时才恢复
      this.selectedDatabase = saved
      this.lastSetDbValue = saved;
      // 不再自动设置可视化状态，等待用户手动触发
    }
  }

  // 用户手动开始可视化
  setHasUserInitiatedVisualization(value: boolean) {
    this.hasUserInitiatedVisualization = value;
  }

  // 重置可视化状态
  resetVisualizationState() {
    this.hasUserInitiatedVisualization = false;
    this.visualizationReady = false;
  }

  // 验证数据库是否在可用列表中
  validateDatabaseExists(database: string): boolean {
    return this.availableDatabases.some(db => db.name === database);
  }

  // 获取数据库列表
  async loadDatabases() {
    // 防止重复调用
    if (this.isLoadingDatabases) {
      return [];
    }

    this.isLoadingDatabases = true;

    try {
      const response = await fetch(`${SERVER_URL}/databases`)
      if (response.ok) {
        const databases = await response.json()
        this.setAvailableDatabases(databases)
        return databases
      }
    } catch (error) {
    } finally {
      this.isLoadingDatabases = false;
    }

    return []
  }
}

export const storeGlobalUser = new GlobalUser()
