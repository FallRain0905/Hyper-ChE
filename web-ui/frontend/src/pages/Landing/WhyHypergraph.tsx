import { Link } from 'react-router-dom'
import { ArrowLeft, Beaker, GitBranch, Network, Route } from 'lucide-react'

const ExampleCard = ({ title, question, graph, hypergraph }: { title: string; question: string; graph: string; hypergraph: string }) => (
  <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
    <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
    <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm leading-7 text-slate-700">
      <span className="font-medium text-slate-950">示例问题：</span>{question}
    </div>
    <div className="mt-5 grid gap-4 md:grid-cols-2">
      <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-blue-800">
          <GitBranch size={16} />
          普通图表达
        </div>
        <p className="text-sm leading-7 text-blue-950">{graph}</p>
      </div>
      <div className="rounded-lg border border-violet-100 bg-violet-50 p-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-violet-800">
          <Network size={16} />
          超图表达
        </div>
        <p className="text-sm leading-7 text-violet-950">{hypergraph}</p>
      </div>
    </div>
  </div>
)

const WhyHypergraph = () => (
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
      <div className="mb-10 max-w-3xl">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-teal-100 bg-teal-50 px-3 py-1 text-sm text-teal-800">
          <Beaker size={15} />
          Hypergraph for Chemical Engineering
        </div>
        <h1 className="text-3xl font-semibold leading-tight text-slate-950 md:text-4xl">
          化工知识天然包含多实体共同成立的高阶关系
        </h1>
        <p className="mt-5 text-base leading-8 text-slate-600">
          在化工文献中，许多结论并不是“实体 A 影响实体 B”这么简单，而是由体系、材料、组成、条件、指标和机理证据共同构成。超图允许一条超边同时连接多个实体，因此更适合表达完整实验事实。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {[
          ['事实完整性', '一条超边保留同一实验事实中的材料、条件和指标，避免拆成多条边后丢失共同约束。'],
          ['检索扩散能力', '从一个实体命中后，可以沿超边扩散到同一实验事实中的其他关键变量。'],
          ['机制解释能力', '把表征证据、活性物种、路径和性能结果放入同一个结构单元中，支持机制链条回答。'],
        ].map(([title, desc]) => (
          <div key={title} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
              <Route size={19} />
            </div>
            <h2 className="font-semibold text-slate-950">{title}</h2>
            <p className="mt-2 text-sm leading-7 text-slate-600">{desc}</p>
          </div>
        ))}
      </div>

      <div className="mt-8 space-y-5">
        <ExampleCard
          title="例 1：液流电池性能不是单一材料决定的"
          question="在 100 mA cm^-2 以上电流密度下，哪些膜材料或电极材料仍能保持较高 CE、VE 或 EE？"
          graph="普通图会把“膜-指标”“电极-指标”“电流密度-指标”拆成多条二元边，难以确认这些条件是否来自同一实验组合。"
          hypergraph="超图把电池体系、膜、电极、电流密度、电解液和 CE/VE/EE 放在同一条 OPERATION_PERFORMANCE 超边中召回。"
        />
        <ExampleCard
          title="例 2：PFAS 降解需要同时追踪材料、条件和证据"
          question="哪些催化体系支持直接电子转移导致 C-F 键断裂，而不是只依赖 ROS 路径？"
          graph="普通图能找到材料和活性物种的局部关系，但容易把 EPR、捕获剂实验、LC-MS 中间体和氟离子释放分散开。"
          hypergraph="超图把 PFAS 目标物、催化材料、过程策略、活性物种、机理证据和脱氟指标组织为 MECHANISM_PATHWAY 超边。"
        />
        <ExampleCard
          title="例 3：配方检索本质上是条件组合检索"
          question="哪些实验同时满足高能量效率、低交叉污染和较高电流密度？"
          graph="普通向量检索能找到相关段落，但难以保证“高效率”“低 crossover”“高电流密度”属于同一配方。"
          hypergraph="超图检索可以围绕同一超边展开，优先返回共同参与同一实验事实的实体集合。"
        />
      </div>
    </main>
  </div>
)

export default WhyHypergraph
