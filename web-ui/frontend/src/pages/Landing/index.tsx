import type React from 'react'
import { useEffect, useMemo, useState } from 'react'
import { observer } from 'mobx-react'
import { Link, useNavigate } from 'react-router-dom'
import { message } from 'antd'
import {
  ArrowRight,
  Atom,
  Beaker,
  Database,
  KeyRound,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { authStore } from '@/store/auth'

type AuthMode = 'login' | 'register'

const FeatureCard = ({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) => (
  <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
    <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
      {icon}
    </div>
    <h3 className="text-base font-semibold text-slate-950">{title}</h3>
    <p className="mt-2 text-sm leading-6 text-slate-600">{desc}</p>
  </div>
)

const ComparisonColumn = ({ title, items, accent }: { title: string; items: string[]; accent: string }) => (
  <div className="rounded-lg border border-slate-200 bg-white p-5">
    <div className="mb-4 flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${accent}`} />
      <h3 className="text-base font-semibold text-slate-950">{title}</h3>
    </div>
    <div className="space-y-3">
      {items.map(item => (
        <div key={item} className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
          {item}
        </div>
      ))}
    </div>
  </div>
)

const Landing = () => {
  const navigate = useNavigate()
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [loading, setLoading] = useState(false)
  const isSubmitting = loading || authStore.loading

  useEffect(() => {
    if (!authStore.initialized) {
      authStore.fetchMe()
    }
  }, [])

  const authTitle = useMemo(() => (mode === 'login' ? '登录 HyperChE' : '创建试用账号'), [mode])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const nextEmail = email.trim()
    const nextDisplayName = displayName.trim()
    if (!nextEmail) {
      message.warning('请输入邮箱')
      return
    }
    if (password.length < 8) {
      message.warning('密码至少需要 8 位')
      return
    }
    setLoading(true)
    try {
      if (mode === 'login') {
        await authStore.login(nextEmail, password)
        message.success('登录成功')
      } else {
        await authStore.register(nextEmail, password, nextDisplayName)
        message.success('注册成功，已进入试用')
      }
      navigate('/app/Hyper/chat')
    } catch (error: any) {
      message.error(error.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  const authPanel = (
    <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-6 flex rounded-lg bg-slate-100 p-1">
        <button
          type="button"
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${mode === 'login' ? 'bg-white text-teal-800 shadow-sm' : 'text-slate-600'}`}
          onClick={() => setMode('login')}
        >
          登录
        </button>
        <button
          type="button"
          className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${mode === 'register' ? 'bg-white text-teal-800 shadow-sm' : 'text-slate-600'}`}
          onClick={() => setMode('register')}
        >
          注册
        </button>
      </div>

      <h2 className="text-xl font-semibold text-slate-950">{authTitle}</h2>
      <p className="mt-2 text-sm text-slate-600">
        注册账号后可进入完整工作台；公开试用无需登录，使用示例化工知识库。
      </p>

      <form className="mt-6 space-y-4" onSubmit={submit}>
        {mode === 'register' && (
          <label className="block">
            <span className="text-sm font-medium text-slate-700">昵称</span>
            <input
              value={displayName}
              onChange={event => setDisplayName(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600"
              placeholder="你的名字或课题组名称"
              autoComplete="name"
            />
          </label>
        )}
        <label className="block">
          <span className="text-sm font-medium text-slate-700">邮箱</span>
          <input
            value={email}
            onChange={event => setEmail(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600"
            placeholder="name@example.com"
            type="email"
            autoComplete="email"
            required
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">密码</span>
          <input
            value={password}
            onChange={event => setPassword(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600"
            placeholder="至少 8 位"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={8}
            required
          />
        </label>
        <button
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-teal-700 px-4 py-3 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-60"
          disabled={isSubmitting}
          type="submit"
        >
          {isSubmitting ? '处理中...' : mode === 'login' ? '登录并进入工作台' : '注册并开始试用'}
          <ArrowRight size={16} />
        </button>
      </form>

      <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
        <div className="mb-1 flex items-center gap-2 font-medium">
          <KeyRound size={16} />
          使用自己的 API Key
        </div>
        登录后可在设置页批量添加 LLM 与 embedding API Key。系统会优先使用个人 Key；未配置时使用平台试用额度。
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-950">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <button className="flex items-center gap-3" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-700 text-sm font-semibold text-white">
              HC
            </div>
            <div className="text-left">
              <div className="text-lg font-semibold">HyperChE</div>
              <div className="text-xs text-slate-500">Hypergraph for Chemical Engineering</div>
            </div>
          </button>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-slate-200 bg-white">
          <div className="mx-auto grid max-w-7xl gap-10 px-6 py-16 lg:grid-cols-[1.08fr_0.92fr] lg:py-20">
            <div className="flex flex-col justify-center">
              <div className="mb-5 inline-flex w-fit items-center gap-2 rounded-full border border-teal-100 bg-teal-50 px-3 py-1 text-sm text-teal-800">
                <Sparkles size={15} />
                面向化工知识高阶关系表达
              </div>
              <h1 className="max-w-3xl text-4xl font-semibold leading-tight text-slate-950 md:text-5xl">
                HyperChE
                <span className="mt-3 block text-2xl font-medium text-slate-700 md:text-3xl">
                  化工文献的超图知识建模与增强检索平台
                </span>
              </h1>
              <p className="mt-6 max-w-2xl text-base leading-8 text-slate-600">
                将化工文献中的体系、材料、条件、指标与机理证据组织为高阶超边，帮助研究者从文献片段中恢复完整实验事实，而不只是找到语义相似文本。
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  to="/try"
                  className="inline-flex items-center gap-2 rounded-lg bg-teal-700 px-5 py-3 text-sm font-medium text-white hover:bg-teal-800"
                >
                  开始试用 <ArrowRight size={16} />
                </Link>
                <Link
                  to="/why-hypergraph"
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-5 py-3 text-sm font-medium text-slate-700 hover:border-teal-200 hover:text-teal-700"
                >
                  显示超图优势
                </Link>
              </div>
            </div>
            {authPanel}
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-14">
          <div className="mb-8 max-w-2xl">
            <h2 className="text-2xl font-semibold text-slate-950">为什么化工知识需要超图</h2>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              化工实验事实通常由多个变量共同约束。HyperChE 将多元关系作为完整超边保留，减少普通图拆边带来的上下文碎片化。
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <FeatureCard
              icon={<Beaker size={20} />}
              title="体系-材料-条件-指标"
              desc="把电池体系、膜/电极、电解液组成、操作条件和性能指标作为同一事实单元召回。"
            />
            <FeatureCard
              icon={<Atom size={20} />}
              title="机理证据链"
              desc="关联活性物种、表征证据、降解路径、脱氟或容量衰减现象，支持机制型问答。"
            />
            <FeatureCard
              icon={<Database size={20} />}
              title="领域可迁移"
              desc="通过实体类型、关系类型和提示词配置，扩展到液流电池、PFAS 降解等化工子领域。"
            />
          </div>
        </section>

        <section className="border-y border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-6 py-14">
            <h2 className="text-2xl font-semibold text-slate-950">当前验证案例</h2>
            <div className="mt-6 grid gap-4 md:grid-cols-2">
              <Link to="/demo/flow-battery" className="rounded-lg border border-slate-200 bg-slate-50 p-5 transition hover:border-teal-300 hover:bg-white">
                <div className="text-sm font-medium text-teal-700">Case 1</div>
                <h3 className="mt-2 text-lg font-semibold text-slate-950">液流电池</h3>
                <p className="mt-2 text-sm leading-7 text-slate-600">
                  面向 VRFB、ICRFB、锌基、有机和多硫化物-溴体系，建模活性物质、膜、电极、操作条件与效率指标之间的高阶组合。
                </p>
              </Link>
              <Link to="/demo/pfas" className="rounded-lg border border-slate-200 bg-slate-50 p-5 transition hover:border-blue-300 hover:bg-white">
                <div className="text-sm font-medium text-blue-700">Case 2</div>
                <h3 className="mt-2 text-lg font-semibold text-slate-950">PFAS 降解</h3>
                <p className="mt-2 text-sm leading-7 text-slate-600">
                  面向 PFAS/PFOA/PFOS 等污染物去除、降解、脱氟和矿化，组织催化材料、条件、活性物种和机理证据。
                </p>
              </Link>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-6 py-14">
          <h2 className="text-2xl font-semibold text-slate-950">从文本相似到高阶事实召回</h2>
          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <ComparisonColumn
              title="Vector RAG"
              accent="bg-slate-400"
              items={['召回语义相似文本', '难以判断多变量是否同时成立', '回答依赖片段拼接']}
            />
            <ComparisonColumn
              title="Graph RAG"
              accent="bg-blue-600"
              items={['实体-关系-实体', '多变量事实被拆成二元边', '同一实验条件容易丢失']}
            />
            <ComparisonColumn
              title="Hypergraph RAG"
              accent="bg-violet-600"
              items={['一条超边连接多个实体', '保留完整实验事实单元', '适合条件组合与机理链条问题']}
            />
          </div>
          <div className="mt-8 rounded-lg border border-teal-200 bg-teal-50 p-5 text-sm leading-7 text-teal-950">
            <div className="mb-2 flex items-center gap-2 font-semibold">
              <ShieldCheck size={18} />
              公测试用策略
            </div>
            首页“开始试用”进入公开示例库，不需要登录即可体验问答和超图可视化。正式上传文献和创建知识库需要登录，并建议配置个人 API Key。
          </div>
        </section>
      </main>
    </div>
  )
}

export default observer(Landing)
