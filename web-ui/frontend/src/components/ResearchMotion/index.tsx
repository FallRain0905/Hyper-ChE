import { useEffect, useRef, useState } from 'react'

type Props = { effect: 'intro' | 'constellation'; className?: string }
const introSeen = () => {
  try { return sessionStorage.getItem('hyperche_intro_seen') === '1' } catch { return false }
}
export default function ResearchMotion({ effect, className = '' }: Props) {
  const frame = useRef<HTMLIFrameElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const [source, setSource] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [staticIntro] = useState(() => effect === 'intro' && introSeen())
  useEffect(() => {
    if (staticIntro) return
    let alive = true
    const load = effect === 'intro' ? import('./sources/intro.html?raw') : import('./sources/constellation.html?raw')
    load.then(module => { if (alive) setSource(module.default) })
    return () => { alive = false }
  }, [effect, staticIntro])
  useEffect(() => {
    if (!host.current || !loaded) return
    let visible = true
    const post = () => frame.current?.contentWindow?.postMessage({ type: 'hyperche-motion', action: visible && !document.hidden ? 'resume' : 'pause' }, '*')
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; post() })
    observer.observe(host.current)
    document.addEventListener('visibilitychange', post)
    post()
    if (effect === 'intro') {
      try { sessionStorage.setItem('hyperche_intro_seen', '1') } catch { /* Session storage is optional. */ }
    }
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', post) }
  }, [loaded, effect])
  return <div ref={host} className={`research-motion research-motion-${effect} ${className}`} aria-hidden="true">
    {staticIntro || !source ? (effect === 'intro' ? <span className="research-static-wordmark">HyperChE</span> : null) : <iframe ref={frame} srcDoc={source} title={`${effect} visual`} sandbox="allow-scripts" tabIndex={-1} onLoad={() => setLoaded(true)} />}
  </div>
}
