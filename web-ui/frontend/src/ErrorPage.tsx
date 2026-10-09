import { useEffect } from 'react'
import { useRouteError } from 'react-router-dom'

const ErrorPage = () => {
  const error: any = useRouteError()
  useEffect(() => {
    // A release can replace lazy-loaded assets while an older tab is open.
    // Retry once; a persistent outage must not create a reload loop.
    if (!String(error?.message || '').includes('dynamically imported module')) return
    try {
      const key = 'hyperche:asset-reload-at'
      const previous = Number(sessionStorage.getItem(key) || 0)
      if (Date.now() - previous < 30_000) return
      sessionStorage.setItem(key, String(Date.now()))
      window.location.reload()
    } catch { /* Storage may be disabled; keep the explicit recovery button. */ }
  }, [error])
  return <main className="research-page" style={{ minHeight: '100dvh', padding: '64px 24px' }}>
    <section className="research-panel" style={{ maxWidth: 540, margin: 'auto', padding: 28 }}>
      <h1 style={{ fontSize: 24 }}>页面暂时无法加载</h1>
      <p className="research-muted" style={{ margin: '16px 0' }}>请检查网络后重新加载页面。已保存的会话仍会保留。</p>
      <button type="button" className="research-primary" onClick={() => window.location.reload()}>重新加载页面</button>
      <a className="research-secondary" href="/" style={{ marginLeft: 8 }}>返回首页</a>
    </section>
  </main>
}
export default ErrorPage
