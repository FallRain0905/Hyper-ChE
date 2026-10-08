import { lazy, Suspense, useEffect, useState } from 'react'
import { observer } from 'mobx-react'
import { Link, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { ArrowRight } from 'lucide-react'
import { authStore } from '@/store/auth'
import ResearchDock from '@/components/ResearchDock'
const ResearchMotion = lazy(() => import('@/components/ResearchMotion'))

function Landing() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!authStore.initialized) authStore.fetchMe().catch(() => undefined) }, [])
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!email.trim() || !password) return message.warning('请填写邮箱和密码')
    if (mode === 'register' && password.length < 8) return message.warning('注册密码至少需要 8 位')
    setBusy(true)
    try {
      if (mode === 'login') await authStore.login(email.trim(), password)
      else await authStore.register(email.trim(), password, name.trim())
      navigate(authStore.isAdmin ? '/app/admin' : '/app/Hyper/chat')
    } catch (error: any) { message.error(error?.message || '操作失败') } finally { setBusy(false) }
  }
  return <div className="research-page" style={{ minHeight: '100dvh' }}>
    <ResearchDock publicPage actions={authStore.isAuthenticated ? <button className="research-primary" onClick={() => navigate('/app/Hyper/chat')}>进入工作台</button> : undefined} />
    <main className="research-landing">
      <section>
        <div className="research-eyebrow">Hypergraph Chemical Engine</div>
        <Suspense fallback={<div className="research-static-wordmark">HyperChE</div>}><ResearchMotion effect="intro" /></Suspense>
        <h1 className="research-title">把实体、实验条件与结果<br />保留在同一条知识关系中</h1>
        <p className="research-lead">HyperChE 面向化工与材料文献，用超图组织多实体关系，结合语义检索与结构排序，返回答案及其来源证据。</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 24 }}><Link to="/try" className="research-primary">查看公开体验 <ArrowRight size={15} /></Link><Link to="/why-hypergraph" className="research-secondary">了解超图表示</Link></div>
        <div className="research-hero-diagram"><Suspense fallback={null}><ResearchMotion effect="constellation" /></Suspense><div className="research-hero-steps"><span>文献与知识库</span><ArrowRight size={15} /><span>实体 · 条件 · 超边</span><ArrowRight size={15} /><span>检索证据与回答</span></div></div>
        <div className="research-facts"><span>多实体关系</span><span>原始证据可追溯</span><span>只读公开知识库</span></div>
        <p className="research-muted" style={{ marginTop: 18, fontSize: 12 }}>公开体验的模型渠道由管理员维护；渠道未配置时仍可查看真实缓存超图和项目汇报。已登录用户可以添加个人 API 渠道。</p>
      </section>
      <section className="research-panel research-auth">
        <div className="research-eyebrow">Research workspace</div><h2 style={{ fontSize: 22, margin: '10px 0 6px' }}>{mode === 'login' ? '登录工作台' : '创建试用账号'}</h2><p className="research-muted" style={{ fontSize: 12, marginBottom: 20 }}>管理知识库、提出问题、核对来源。</p>
        <div className="research-auth-tabs" role="tablist" aria-label="账号操作"><button role="tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>登录</button><button role="tab" aria-selected={mode === 'register'} onClick={() => setMode('register')}>注册</button></div>
        <form onSubmit={submit}>{mode === 'register' && <label>昵称<input autoComplete="name" value={name} onChange={event => setName(event.target.value)} placeholder="你的名字或团队" /></label>}<label>邮箱<input type="email" required autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="name@example.com" /></label><label>密码<input type="password" required minLength={mode === 'register' ? 8 : undefined} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} placeholder={mode === 'register' ? '至少 8 位' : '输入密码'} /></label><button disabled={busy || authStore.loading} className="research-primary" style={{ width: '100%', marginTop: 22 }}>{busy ? '正在处理…' : mode === 'login' ? '登录' : '创建账号'}</button></form>
        <p className="research-muted" style={{ fontSize: 11, marginTop: 16 }}>公共渠道密钥由服务器管理，不会显示在页面中。</p>
      </section>
    </main>
  </div>
}
export default observer(Landing)
