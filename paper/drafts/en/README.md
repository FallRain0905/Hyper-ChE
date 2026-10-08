# HyperChE arXiv 草稿工作区

当前依据：`05_reports/arxiv_paper_outline_v2.md`。

## 统一写作要求

- 论文语言：英文；内部说明可用中文。
- 题目暂定：HyperChE: Normalized Hypergraph Retrieval for High-Order Chemical Facts。
- 只使用已审计数字：60 documents、1,328 chunks、58 queries、4,196 judged query/chunk pairs、150 accepted atomic facts；F1 Hit@5 0.6724、MRR 0.4684、gNDCG@5 0.3873、CFR@5 0.4267。
- 主组：B0 original hypergraph、B1 chem prompt graph、B2 chem prompt hypergraph、F0 normalized final no rerank、F1 normalized final。
- 不把 B1/B2 写成严格单变量实验；B2 低于 B1 必须解释为检索入口、quota、排序和超边文本化共同作用。
- 不回显任何 API key。
- QA 服务条件必须披露：历史组 Moonshot，F1 使用阿里云 DashScope；不能宣称完全一致。
- source-level 指标是由 chunk qrels 推导的诊断，不是独立 source-level gold。
- 避免无证据的显著性、因果和跨领域泛化表述。

## 文件分工

- `01_abstract_introduction.md`
- `02_related_work_problem.md`
- `03_method.md`
- `04_experimental_setup.md`
- `05_results_discussion.md`
- `06_limitations_conclusion.md`
- `07_master_draft.md`（由主代理统一合并，含附录）
- `08_appendices.md`

## 当前状态

`07_master_draft.md` 已合并 Abstract、Introduction、Related Work、Problem Definition、Method、Experimental Setup、Results and Discussion、Limitations 和 Conclusion。它是英文工作草稿，尚未进行 LaTeX 排版、参考文献编译或最终数字审计。
