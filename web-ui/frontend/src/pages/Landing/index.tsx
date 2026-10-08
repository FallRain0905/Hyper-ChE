import type React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { observer } from 'mobx-react'
import { Link, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import {
  ArrowRight,
  Database,
  FlaskConical,
  KeyRound,
  Network,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { authStore } from '@/store/auth'
import { PUBLIC_DEMO } from '@/config/publicDemo'

type AuthMode = 'login' | 'register'

const Landing = () => {
  const navigate = useNavigate()
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [loading, setLoading] = useState(false)
  const isSubmitting = loading || authStore.loading

  useEffect(() => {
    if (!authStore.initialized) authStore.fetchMe()
  }, [])

  const authTitle = useMemo(() => mode === 'login' ? '进入 HyperChE 工作台' : '创建免费试用账号', [mode])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const nextEmail = email.trim()
    if (!nextEmail) return message.warning('请输入邮箱')
    if (!password) return message.warning('请输入密码')
    if (mode === 'register' && password.length < 8) return message.warning('注册密码至少需要 8 位')
    setLoading(true)
    try {
      if (mode === 'login') {
        await authStore.login(nextEmail, password)
        message.success('登录成功')
      } else {
        await authStore.register(nextEmail, password, displayName.trim())
        message.success('注册成功，已进入免费试用')
      }
      navigate(authStore.isAdmin ? '/app/admin' : '/app/Hyper/chat')
    } catch (error: any) {
      message.error(error?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen overflow-hidden bg-[#f7f8fa] text-slate-950">
      <div className="hyperche-grid pointer-events-none fixed inset-0 opacity-35" />
      <div className="hyperche-drift pointer-events-none fixed -left-40 top-24 h-[30rem] w-[30rem] rounded-full bg-blue-200/35 blur-3xl" />
      <div className="hyperche-drift-reverse pointer-events-none fixed -right-40 top-1/3 h-[28rem] w-[28rem] rounded-full bg-violet-200/25 blur-3xl" />

      <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/75 backdrop-blur-2xl">
        <div className="mx-auto flex h-[70px] w-full max-w-7xl items-center justify-between px-5 lg:px-8">
          <Link to="/" className="group flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-950 text-xs font-bold text-white shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md">HC</span>
            <span><span className="block text-sm font-semibold tracking-wide text-slate-950">HyperChE</span><span className="block text-[10px] font-medium tracking-[0.12em] text-slate-400">Hypergraph Chemical Engine</span></span>
          </Link>
          <nav className="flex items-center gap-2">
            <Link to="/why-hypergraph" className="hidden rounded-xl px-3 py-2 text-sm text-slate-500 transition hover:bg-slate-100 hover:text-slate-950 sm:block">为什么用超图</Link>
            <Link to={PUBLIC_DEMO.route} className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300">公开体验</Link>
            {authStore.isAuthenticated && <button onClick={() => navigate(authStore.isAdmin ? '/app/admin' : '/app/Hyper/chat')} className="rounded-xl bg-slate-950 px-3.5 py-2 text-sm font-medium text-white transition hover:-translate-y-0.5 hover:bg-slate-800">进入工作台</button>}
          </nav>
        </div>
      </header>

      <main className="relative mx-auto grid min-h-[calc(100vh-70px)] w-full max-w-7xl gap-10 px-5 py-10 lg:grid-cols-[minmax(0,1fr)_430px] lg:items-center lg:px-8 lg:py-14">
        <section className="hyperche-reveal">
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50/90 px-3 py-1.5 text-xs font-semibold text-blue-700 shadow-sm"><Sparkles className="h-3.5 w-3.5" />面向化学与材料研究的超图 RAG 引擎</div>
          <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.08] tracking-[-0.04em] text-slate-950 sm:text-5xl lg:text-[3.7rem]">让复杂科研知识<br/><span className="bg-gradient-to-r from-blue-700 via-blue-600 to-violet-600 bg-clip-text text-transparent">成为可验证的答案</span></h1>
          <p className="mt-5 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg">以超图连接实体、关系、实验条件与原始证据，在一个克制、清晰的工作台中完成检索、问答、图谱分析与文档处理。</p>

          <div className="mt-7 flex flex-wrap gap-3">
            {[{icon:<Network className="h-4 w-4"/>,text:'超图原生组织'},{icon:<Search className="h-4 w-4"/>,text:'证据可追溯'},{icon:<ShieldCheck className="h-4 w-4"/>,text:'个人空间隔离'}].map(item => <div key={item.text} className="hyperche-card flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/80 px-3.5 py-2.5 text-sm font-medium text-slate-700 shadow-sm backdrop-blur">{item.icon}{item.text}</div>)}
          </div>

          <div className="mt-9 grid gap-4 sm:grid-cols-2">
            <div className="hyperche-card rounded-[1.75rem] border border-slate-200 bg-white/85 p-5 shadow-sm backdrop-blur"><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700"><Database className="h-5 w-5"/></span><div><p className="text-xs text-slate-400">Cache status</p><p className="font-semibold text-slate-900">Flow Battery · Ready</p></div></div><div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="hyperche-shimmer h-full w-full rounded-full bg-gradient-to-r from-emerald-500 via-blue-500 to-emerald-500" /></div></div>
            <div className="hyperche-card rounded-[1.75rem] border border-slate-200 bg-slate-950 p-5 text-white shadow-sm"><FlaskConical className="h-5 w-5 text-blue-300"/><p className="mt-5 text-xs text-slate-400">Evidence-linked answer</p><p className="mt-1 text-sm font-medium leading-6">“对比不同电解液条件下的库仑效率，并定位原始证据。”</p><Link to={PUBLIC_DEMO.route} className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-blue-300 hover:text-blue-200">查看公开实例 <ArrowRight className="h-3.5 w-3.5"/></Link></div>
          </div>
        </section>

        <section className="hyperche-reveal-delayed relative">
          <div className="absolute -inset-5 rounded-[2.5rem] bg-gradient-to-br from-blue-200/30 via-transparent to-violet-200/30 blur-2xl" />
          <div className="hyperche-card relative rounded-[2rem] border border-slate-200/90 bg-white/90 p-6 shadow-[0_24px_80px_rgba(15,23,42,.10)] backdrop-blur-2xl sm:p-7">
            <div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Research workspace</p><h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">{authTitle}</h2><p className="mt-1 text-sm leading-6 text-slate-500">使用每日免费额度，或登录后添加个人 API。</p></div><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-700"><KeyRound className="h-5 w-5"/></div></div>
            <div className="mt-6 grid grid-cols-2 rounded-2xl border border-slate-200 bg-slate-100/80 p-1">{(['login','register'] as AuthMode[]).map(item => <button key={item} type="button" onClick={() => setMode(item)} className={`rounded-xl px-3 py-2.5 text-sm font-medium transition ${mode===item?'bg-white text-slate-950 shadow-sm':'text-slate-500 hover:text-slate-900'}`}>{item==='login'?'登录':'注册'}</button>)}</div>
            <form className="mt-5 space-y-4" onSubmit={submit}>
              {mode==='register' && <label className="block"><span className="text-sm font-medium text-slate-700">昵称</span><input value={displayName} onChange={e=>setDisplayName(e.target.value)} className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" placeholder="你的名字或团队名称" autoComplete="name"/></label>}
              <label className="block"><span className="text-sm font-medium text-slate-700">邮箱</span><input value={email} onChange={e=>setEmail(e.target.value)} className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" placeholder="name@example.com" type="email" autoComplete="email"/></label>
              <label className="block"><span className="text-sm font-medium text-slate-700">密码</span><input value={password} onChange={e=>setPassword(e.target.value)} className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition hover:border-slate-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10" placeholder={mode==='register'?'至少 8 位':'请输入登录密码'} type="password" autoComplete={mode==='login'?'current-password':'new-password'}/></label>
              <button disabled={isSubmitting} className="group flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 py-3.5 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-800 hover:shadow-md disabled:translate-y-0 disabled:opacity-60">{isSubmitting?'正在处理…':mode==='login'?'登录工作台':'创建免费账号'}{!isSubmitting&&<ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5"/>}</button>
            </form>
            <div className="mt-5 flex items-start gap-2.5 rounded-2xl border border-blue-100 bg-blue-50/70 px-3.5 py-3 text-xs leading-5 text-blue-800"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0"/>平台公共 API 密钥由管理员安全维护，普通用户不会看到密钥明文。</div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default observer(Landing)
