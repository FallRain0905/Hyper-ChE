import { useEffect, useState } from 'react'
import { observer } from 'mobx-react'
import { Link, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import { authStore } from '@/store/auth'
import ResearchDock from '@/components/ResearchDock'

function Login() {
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
    <main style={{ width: '100%', maxWidth: 470, margin: 'auto', padding: '48px 20px' }}>
      {authStore.isAuthenticated ? <section className="research-panel research-auth">
        <div className="research-eyebrow">Research workspace</div>
        <h1 style={{ fontSize: 24, margin: '10px 0' }}>已登录工作台</h1>
        <p className="research-muted" style={{ margin: '16px 0', overflowWrap: 'anywhere' }}>{authStore.user?.email}</p>
        <Link className="research-primary" to={authStore.isAdmin ? '/app/admin' : '/app/Hyper/chat'}>进入工作台</Link>
        <button type="button" className="research-secondary" style={{ marginLeft: 8 }} onClick={() => { void authStore.logout() }}>退出登录</button>
      </section> :
      <section className="research-panel research-auth">
        <div className="research-eyebrow">Research workspace</div><h2 style={{ fontSize: 22, margin: '10px 0 6px' }}>{mode === 'login' ? '登录工作台' : '创建试用账号'}</h2><p className="research-muted" style={{ fontSize: 12, marginBottom: 20 }}>管理知识库、提出问题、核对来源。</p>
        <div className="research-auth-tabs" role="tablist" aria-label="账号操作"><button role="tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>登录</button><button role="tab" aria-selected={mode === 'register'} onClick={() => setMode('register')}>注册</button></div>
        <form onSubmit={submit}>{mode === 'register' && <label>昵称<input autoComplete="name" value={name} onChange={event => setName(event.target.value)} placeholder="你的名字或团队" /></label>}<label>邮箱<input type="email" required autoComplete="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="name@example.com" /></label><label>密码<input type="password" required minLength={mode === 'register' ? 8 : undefined} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} placeholder={mode === 'register' ? '至少 8 位' : '输入密码'} /></label><button disabled={busy || authStore.loading} className="research-primary" style={{ width: '100%', marginTop: 22 }}>{busy ? '正在处理…' : mode === 'login' ? '登录' : '创建账号'}</button></form>
        <p className="research-muted" style={{ fontSize: 11, marginTop: 16 }}>公共渠道密钥由服务器管理，不会显示在页面中。</p>
      </section>}
      <div style={{ display: 'flex', gap: 18, justifyContent: 'center', marginTop: 24, fontSize: 13 }}><a href="/" className="research-muted">返回项目首页</a><Link to="/try" className="research-muted">公开体验</Link></div>
    </main>
  </div>
}
export default observer(Login)
