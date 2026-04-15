import { makeAutoObservable } from 'mobx'
import { SERVER_URL } from '../utils'

class GlobalUser {
  userInfo: Partial<User.UserEntity> = {}
  selectedDatabase: string = ''
  availableDatabases: Array<{ name: string; description: string }> = []
  private isLoadingDatabases: boolean = false
  private lastSetDbValue: string = ''

  constructor() {
    makeAutoObservable(this)
  }

  async getUserDetail() {
    // const res = await getCurrentUserInfo()
    // this.userInfo = res?.data
    // new WebSee(res?.data?.username)
    this.userInfo = {
      roles: [
        {
          id: 5,
          name: '超级管理员',
          description: '拥有所有查看和操作功能',
          adminCount: 0,
          status: 1,
          sort: 5
        }
      ],
      icon: 'http://jinpika-1308276765.cos.ap-shanghai.myqcloud.com/bootdemo-file/20221220/src=http___desk-fd.zol-img.com.cn_t_s960x600c5_g2_M00_00_0B_ChMlWl6yKqyILFoCACn-5rom2uIAAO4DgEODxAAKf7-298.jpg&refer=http___desk-fd.zol-img.com.png',
      username: 'admin'
    }
  }

  setUserInfo(user: Partial<User.UserEntity>) {
    this.userInfo = user
  }

  // 设置当前选中的数据库
  setSelectedDatabase(database: string) {
    console.log('[GlobalUser] setSelectedDatabase 被调用:', database, '当前 lastSetDbValue:', this.lastSetDbValue);
    // 防止重复设置相同值
    if (this.lastSetDbValue === database) {
      console.log('[GlobalUser] 跳过重复设置');
      return;
    }
    this.lastSetDbValue = database;
    this.selectedDatabase = database
    // 保存到localStorage
    localStorage.setItem('selectedDatabase', database)
    console.log('[GlobalUser] selectedDatabase 已更新为:', database);
  }

  // 设置可用数据库列表
  setAvailableDatabases(databases: Array<{ name: string; description: string }>) {
    console.log('[GlobalUser] setAvailableDatabases 被调用，数据库数量:', databases.length);
    this.availableDatabases = databases

    // 检查当前选择的数据库是否还在列表中
    if (this.selectedDatabase && !databases.find(db => db.name === this.selectedDatabase)) {
      console.log('[GlobalUser] 当前选择的数据库不在列表中，清除选择');
      this.selectedDatabase = '';
      this.lastSetDbValue = '';
      localStorage.removeItem('selectedDatabase');
    }

    // 注意：不再自动修改 selectedDatabase，让用户自己选择
    // 避免循环：不主动调用 setSelectedDatabase，只更新 availableDatabases 状态
  }

  // 从localStorage恢复选中的数据库
  restoreSelectedDatabase() {
    const saved = localStorage.getItem('selectedDatabase')
    console.log('[GlobalUser] restoreSelectedDatabase 被调用, saved:', saved, '当前 selectedDatabase:', this.selectedDatabase);
    if (saved && !this.selectedDatabase) {
      // 只在没有选中数据库时才恢复
      this.selectedDatabase = saved
      this.lastSetDbValue = saved;  // 同时更新 lastSetDbValue 防止被 setSelectedDatabase 阻止
      console.log('[GlobalUser] 已从 localStorage 恢复数据库:', saved);
    }
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
      console.error('加载数据库列表失败:', error)
    } finally {
      this.isLoadingDatabases = false;
    }

    return []
  }
}

export const storeGlobalUser = new GlobalUser()
