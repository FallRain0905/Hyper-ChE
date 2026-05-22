import { Link } from 'react-router-dom'
import { ArrowLeft, BatteryCharging, Network } from 'lucide-react'

const rows = [
  ['体系', '全钒液流电池、铁铬液流电池、锌基液流电池、有机液流电池'],
  ['材料', 'Nafion 系列膜、PBI 类膜、carbon felt、graphite felt、Bi 改性电极'],
  ['条件', '电流密度、流速、温度、酸浓度、活性物质浓度'],
  ['指标', 'CE、VE、EE、capacity retention、crossover、capacity decay'],
  ['机理', 'vanadium crossover、HER、Cr 反应动力学、枝晶生长、PbO2 passivation'],
]

const FlowBatteryDemo = () => (
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
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-teal-100 bg-teal-50 px-3 py-1 text-sm text-teal-800">
          <BatteryCharging size={15} />
          Case 1
        </div>
        <h1 className="text-3xl font-semibold text-slate-950 md:text-4xl">液流电池文献超图建模示例</h1>
        <p className="mt-5 text-base leading-8 text-slate-600">
          该案例用于验证超图对“体系-材料-条件-指标-机理”组合事实的表达能力。页面内容为展示示意，真实回答以工作台知识库检索结果为准。
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-950">领域实体覆盖</h2>
          <div className="mt-5 space-y-3">
            {rows.map(([key, value]) => (
              <div key={key} className="rounded-lg bg-slate-50 p-4">
                <div className="text-sm font-semibold text-teal-800">{key}</div>
                <div className="mt-1 text-sm leading-7 text-slate-700">{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-950">
            <Network size={18} />
            高阶超边示意
          </h2>
          <div className="mt-5 rounded-lg border border-violet-100 bg-violet-50 p-5 text-sm leading-7 text-violet-950">
            <div className="font-semibold">OPERATION_PERFORMANCE</div>
            <div className="mt-3 grid gap-2">
              {['VRFB', 'Nafion 115', 'graphite felt', 'VOSO4 / H2SO4 electrolyte', '100 mA cm^-2', 'CE / VE / EE'].map(item => (
                <span key={item} className="rounded-md bg-white px-3 py-2 text-slate-800 shadow-sm">
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-950">
            示例问题：对铁铬液流电池而言，Bi/Bi3+/BiCl3、glycine、EDTA 等添加剂分别与哪些 Fe/Cr 活性物种、HCl 条件、电极材料和性能指标共同出现？
          </div>
        </div>
      </div>
    </main>
  </div>
)

export default FlowBatteryDemo
