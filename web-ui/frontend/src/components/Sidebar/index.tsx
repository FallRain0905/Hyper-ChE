import type { ReactNode } from 'react'
import { createContext, useContext, useEffect, useState } from 'react'
import { observer } from 'mobx-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { authStore } from '@/store/auth'

interface SidebarContextValue {
  collapsed: boolean
  setCollapsed: (v: boolean) => void
}

const SidebarContext = createContext<SidebarContextValue>({
  collapsed: false,
  setCollapsed: () => undefined,
})

export function useSidebar() {
  return useContext(SidebarContext)
}

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed }}>
      {children}
    </SidebarContext.Provider>
  )
}

interface NavItem {
  path: string
  label: string
  icon: ReactNode
}

const navItems: NavItem[] = [
  {
    path: '/app/Hyper/chat',
    label: '\u68c0\u7d22\u95ee\u7b54',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
      </svg>
    ),
  },
  {
    path: '/app/Hyper/show',
    label: '\u8d85\u56fe\u5c55\u793a',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
      </svg>
    ),
  },
  {
    path: '/app/Hyper/DB',
    label: 'HypergraphDB',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
      </svg>
    ),
  },
  {
    path: '/app/Hyper/FullGraph',
    label: 'FullGraph',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
      </svg>
    ),
  },
  {
    path: '/app/Hyper/files',
    label: '\u77e5\u8bc6\u5e93',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    ),
  },
  {
    path: '/app/Setting',
    label: '\u7cfb\u7edf\u8bbe\u7f6e',
    icon: (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
]

function Sidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { collapsed, setCollapsed } = useSidebar()
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkMobile = () => {
      const mobile = window.innerWidth < 1024
      setIsMobile(mobile)
      if (mobile) {
        setCollapsed(true)
      }
    }

    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [setCollapsed])

  const isActive = (path: string) => {
    const currentPath = location.hash.replace('#', '') || location.pathname
    return currentPath === path || (path !== '/' && currentPath.startsWith(path))
  }

  return (
    <>
      {isMobile && !collapsed && (
        <div
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
          onClick={() => setCollapsed(true)}
        />
      )}

      <aside
        className={`fixed left-0 top-0 z-50 flex h-full flex-col border-r border-slate-200 bg-white transition-all duration-200 ${
          collapsed ? 'w-16' : 'w-60'
        }`}
      >
        <div className="flex h-14 shrink-0 items-center border-b border-slate-100 px-3">
          {!collapsed ? (
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-teal-700 text-xs font-semibold text-white">
                HC
              </div>
              <span className="text-sm font-semibold text-slate-900">HyperChE</span>
            </div>
          ) : (
            <div className="mx-auto flex h-7 w-7 items-center justify-center rounded-md bg-teal-700 text-xs font-semibold text-white">
              HC
            </div>
          )}
          {!isMobile && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="ml-auto rounded p-1 text-slate-400 transition-colors hover:bg-teal-50 hover:text-teal-700"
            >
              <svg
                className={`h-4 w-4 transition-transform ${collapsed ? '' : 'rotate-180'}`}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.5}
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
              </svg>
            </button>
          )}
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3">
          {!collapsed && (
            <div className="mb-1 px-2 text-[10px] font-medium uppercase tracking-wider text-slate-400">
              HyperChE
            </div>
          )}
          {navItems.map(item => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                isActive(item.path)
                  ? 'bg-teal-50 font-medium text-teal-700'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950'
              } ${collapsed ? 'justify-center' : ''}`}
              title={collapsed ? item.label : undefined}
            >
              {item.icon}
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        <div className="shrink-0 border-t border-slate-100 px-2 py-2">
          {!collapsed && (
            <div className="space-y-2 py-1">
              <div className="truncate px-2 text-xs text-slate-500">
                {authStore.user?.email || 'HyperChE user'}
              </div>
              <button
                className="w-full rounded-md px-2 py-1.5 text-xs text-slate-500 hover:bg-teal-50 hover:text-teal-700"
                onClick={() => navigate('/')}
              >
                {'返回首页'}
              </button>
              <button
                className="w-full rounded-md px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-50 hover:text-teal-700"
                onClick={async () => {
                  await authStore.logout()
                  navigate('/')
                }}
              >
                {'\u9000\u51fa\u767b\u5f55'}
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}

export default observer(Sidebar)
