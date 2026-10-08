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
    <div className="relative flex min-h-screen overflow-hidden bg-[#f7f8fa]">
      <div className="hyperche-grid pointer-events-none fixed inset-0 opacity-30" />
      <div className="hyperche-drift pointer-events-none fixed -right-32 top-16 h-80 w-80 rounded-full bg-blue-200/25 blur-3xl" />
      <div className="hyperche-drift-reverse pointer-events-none fixed bottom-0 left-1/3 h-72 w-72 rounded-full bg-violet-200/20 blur-3xl" />
      <Sidebar />
      <div className={`relative z-10 min-w-0 flex-1 transition-all duration-300 ${collapsed ? 'lg:ml-16' : 'lg:ml-60'}`}>
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
