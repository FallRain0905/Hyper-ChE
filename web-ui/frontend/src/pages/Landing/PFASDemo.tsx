import { Link } from 'react-router-dom'
import { ArrowLeft, FlaskConical, Network } from 'lucide-react'

const nodes = ['PFOA / PFOS / GenX', 'BaTiO3 / BiFeO3', 'ultrasound', 'oxygen vacancy', '•OH / e−', 'EPR / LC-MS', 'defluorination']

const PFASDemo = () => (
  <div className="min-h-screen bg-[#F8FAFC] text-slate-950">
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link to="/" className="flex items-center gap-3 text-sm font-medium text-slate-700 hover:text-teal-700">
          <ArrowLeft size={16} />
          返回首页
        </Link>
        <Link to="/app/Hyper/chat" className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800">
          进入工作台
        </Link>
      </div>
    </header>

    <main className="mx-auto max-w-6xl px-6 py-12">
      <div className="mb-8 max-w-3xl">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-sm text-blue-800">
          <FlaskConical size={15} />
          Case 2
        </div>
        <h1 className="text-3xl font-semibold text-slate-950 md:text-4xl">PFAS 降解文献超图建模示例</h1>
        <p className="mt-5 text-base leading-8 text-slate-600">
          该案例关注 PFAS/PFOA/PFOS/GenX 等污染物的去除、降解、脱氟和矿化，强调材料性质、反应条件、活性物种与机理证据之间的联合表达。
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm lg:col-span-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-950">
            <Network size={18} />
            MECHANISM_PATHWAY 超边示意
          </h2>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {nodes.map(node => (
              <div key={node} className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-blue-950">
                {node}
              </div>
            ))}
          </div>
          <div className="mt-5 rounded-lg border border-violet-100 bg-violet-50 p-4 text-sm leading-7 text-violet-950">
            超图将目标污染物、催化材料、压电/耦合过程、材料缺陷、活性物种、表征证据和脱氟指标放在同一机制路径中，便于回答“证据链是否支持某类降解路径”。
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-950">示例问题</h2>
          <div className="mt-4 space-y-3 text-sm leading-7 text-slate-700">
            <div className="rounded-lg bg-slate-50 p-4">哪些材料特征与较高脱氟率共同出现？</div>
            <div className="rounded-lg bg-slate-50 p-4">短链 PFAS 降解需要哪些策略组合？</div>
            <div className="rounded-lg bg-slate-50 p-4">直接电子转移的证据来自哪些实验？</div>
          </div>
        </div>
      </div>
    </main>
  </div>
)

export default PFASDemo
