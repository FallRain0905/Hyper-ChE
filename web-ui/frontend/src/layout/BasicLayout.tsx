import { storeGlobalUser } from '@/store/globalUser'
import { storage } from '@/utils'
import { useAsyncEffect } from 'ahooks'
import { Outlet, useLocation } from 'react-router-dom'
import { observer } from 'mobx-react'
import React from 'react'
import Sidebar, { SidebarProvider, useSidebar } from '@/components/Sidebar'
import { authStore } from '@/store/auth'

export enum ComponTypeEnum {
  MENU,
  PAGE,
  COMPON
}

export const GlobalUserInfo = React.createContext<Partial<User.UserEntity>>({})

function LayoutContent() {
  const { collapsed } = useSidebar()

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <div className={`flex-1 transition-all duration-200 ${collapsed ? 'lg:ml-16' : 'lg:ml-60'}`}>
        <Outlet />
      </div>
    </div>
  )
}

const BasicLayout: React.FC = () => {
  const location = useLocation()
  const pathname = location.hash.replace('#', '')

  useAsyncEffect(async () => {
    if (!authStore.initialized) {
      await authStore.fetchMe()
    }
    if (pathname !== '/login') {
      await storeGlobalUser.getUserDetail()
    }
  }, [])

  return (
    <GlobalUserInfo.Provider value={storeGlobalUser.userInfo}>
      <SidebarProvider>
        <LayoutContent />
      </SidebarProvider>
    </GlobalUserInfo.Provider>
  )
}

export default observer(BasicLayout)
