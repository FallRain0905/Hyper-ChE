import { useEffect, useRef, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BookOpen, Database, FlaskConical, LogIn, Network, Search, SlidersHorizontal } from 'lucide-react'
import { createTopDockController } from './topDockController'

export type DockItem = { id: string; label: string; path: string; icon: ReactNode; external?: boolean }
type Props = { publicPage?: boolean; items?: DockItem[]; actions?: ReactNode }
const workspaceItems: DockItem[] = [
  { id: 'chat', label: '检索问答', path: '/app/Hyper/chat', icon: <Search size={16} /> },
  { id: 'graph', label: '超图浏览', path: '/app/Hyper/show', icon: <Network size={16} /> },
  { id: 'files', label: '知识库', path: '/app/Hyper/files', icon: <Database size={16} /> },
  { id: 'settings', label: '设置', path: '/app/Setting', icon: <SlidersHorizontal size={16} /> },
]
const publicItems: DockItem[] = [
  { id: 'home', label: '项目首页', path: '/', icon: <FlaskConical size={16} />, external: true },
  { id: 'login', label: '登录工作台', path: '/login', icon: <LogIn size={16} /> },
  { id: 'try', label: '公开体验', path: '/try', icon: <Search size={16} /> },
]

// Modern branch adapted from ThreeUI AnimatedTopDock: app branding and route-aware items.
// Spring controller is the author's exact source; see THIRD_PARTY_UI.md.
export default function ResearchDock({ publicPage = false, items, actions }: Props) {
  const nav = useRef<HTMLElement>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const list = items || (publicPage ? publicItems : workspaceItems)
  const itemKey = list.map(item => item.id).join('|')
  useEffect(() => {
    if (!nav.current) return
    return createTopDockController(nav.current, () => ({ proximity: 122, spring: .19, damping: .70, widthGrowth: 17, heightGrowth: 16, drop: 3.5, axis: 'x', distribute: false, lockTrack: true }))
  }, [itemKey])
  return (
    <header className="research-dock" data-dock-frame>
      <button type="button" className="research-brand" onClick={() => window.location.assign('/')} aria-label="HyperChE 首页">
        <span className="research-brand-mark">HC</span><span>HyperChE<small>化工知识检索与问答</small></span>
      </button>
      <nav ref={nav} className="research-dock-nav" aria-label="主要导航" data-dock-state="idle" data-dock-max="0.00">
        {list.map(item => <button key={item.id} type="button" data-dock-item aria-current={!item.external && location.pathname === item.path ? 'page' : undefined} aria-pressed={!item.external && location.pathname === item.path} onClick={() => item.external ? window.location.assign(item.path) : navigate(item.path)}>{item.icon}<span>{item.label}</span></button>)}
      </nav>
      <div className="research-dock-actions"><a href="/#guide"><BookOpen size={15} /><span>项目介绍</span></a>{actions}</div>
    </header>
  )
}
