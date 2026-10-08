export const PUBLIC_DEMO = {
  id: 'flow-battery',
  route: '/try',
  legacyRoute: '/demo/flow-battery',
  database: 'case1',
  name: '液流电池公开知识库',
  shortName: '液流电池实例',
  domain: 'flow_battery',
  description: '固定使用只读液流电池知识库，提供检索问答、检索图和实体邻域超图。',
  suggestedQuestions: [
    '比较 Nafion 117、SPEEK/APK、SPI-DH-6O 和 SPTPC-2.59 在 CE、VE、EE、电流密度、交叉渗透、溶胀和成本上的差异。',
    '为什么 SPTPC-2.59 能在 280 mA cm^-2 下保持约 80% EE？多孔膜策略还存在哪些孔径控制和耐久性风险？',
    'B/N 共掺杂的 BMC-C 电极为什么比 MC-C 和 C-C 更适合高电流密度 VRFB？请结合 200 与 500 mA cm^-2 的性能指标解释。',
    '在铁铬液流电池中，Bi@C 和 glycine 如何共同影响 Cr3+/Cr2+ 动力学与析氢副反应？为什么 EDTA 可能反而降低 VE/EE？',
    '比较 VRFB、ICRFB、锌基、有机和多硫化物-溴液流电池的成熟度、成本、能量密度和主要失效机制。',
    '请用 crossover、HER、polarization 和 current density 的例子解释 CE、VE 与 EE 分别反映什么问题。',
  ],
} as const

export type PublicDemoStatus = {
  success: boolean
  ready: boolean
  database: string
  cache_exists: boolean
  missing_files: string[]
  lfs_pointer_files: string[]
  demo?: {
    id: string
    name: string
    domain: string
  }
}
