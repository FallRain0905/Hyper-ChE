# HyperChE

**Chemical hypergraph retrieval with normalized entities, conditions, measurements and source-grounded evidence.**

HyperChE 面向化工文献检索与问答，在 [Hyper-RAG](https://github.com/iMoonLab/Hyper-RAG) 框架上扩展领域提示词、实体与关系归一化、条件和测量实例、混合检索、结构重排以及 Web 平台。仓库同时提供当前代码、五组最终实验结果和论文草稿。

化工实验中的材料、组成、操作条件、测量值和性能结果共同限定一个事实。HyperChE 用超边保存这些角色的共同范围，保留 canonical/surface 双表示及源文本指针，支持检索匹配和证据核验。当前实验支持归一化超图完整系统在本基准上的收益，不将其推广为所有超图方法的普遍优势。

## 系统流程

1. **构建**：文献分块，抽取领域实体和多元关系，进行归一化与条件/测量实例组织，建立实体、超边索引和源证据关联。
2. **检索**：问题分别检索实体和超边，结合 dense/BM25 与 weighted RRF，扩展关联事实，映射回源文本块，按需进行确定性结构重排。
3. **问答**：从排名靠前的证据组装上下文，生成带来源引用的答案。

Web 平台提供文献上传、知识库管理、超图可视化、提供商通道及密钥池、用户额度和版本化提示包。当前领域提示支持液流电池和 PFAS 压电催化；下面的论文结果仅来自液流电池基准。

## 目录与论文资料

```text
hyperrag/                  核心 RAG 与领域抽取
hyperche/                  归一化 查询处理 提示包
configs/                   实验模式与归一化规则
scripts/                   构建 检索 QA 评价与复现
tests/                     回归测试
web-ui/                    FastAPI 后端与 React 前端
experiments/final_v1/      五组结果 协议 qrels 事实标注
paper/drafts/              英文与中文草稿
paper/latex/               含真实结果图的 LaTeX 源包
paper/figures/             结果图和绘图脚本
paper/figure_plan/         Word 绘图说明
deploy/                    Docker 部署说明
```

- [完整项目结构](PROJECT_STRUCTURE.md)
- [最终实验资料](experiments/final_v1/README.md)
- [论文资料入口](paper/README.md)
- [中文主稿](paper/drafts/zh/07_中文主稿.md)
- [已审阅英文稿](paper/editorial/english_reviewed_v1.md)
- [绘图说明 Word](paper/figure_plan/HyperChE_论文绘图说明_v1.docx)
- [LaTeX 源文件](paper/latex/hyperche_arxiv.tex)

论文目前是第一版草稿，作者信息和三幅方法/示例图仍待完成。`article` 是所选版式，不是 arXiv 强制模板。资料包不等于已完成投稿。

## 最终实验结果

固定语料包含 **60 篇文献、1,328 个文本块、58 个检索问题、4,196 个共享判定对、150 个已接受事实**。Embedding 为 `Qwen/Qwen3-Embedding-4B`，2,560 维；EFU repair 全程关闭。

主检索阈值为 grade ≥ 2，gNDCG@5 使用共同的 IDCG。CFR@5 统计 top-5 中是否包含已接受事实的精确支持文本块。

| 组 | 系统 | Hit@5 | MRR | shared gNDCG@5 | CFR@5 |
| --- | --- | ---: | ---: | ---: | ---: |
| B0 | 原始超图 | 0.4828 | 0.2832 | 0.1779 | 0.0933 |
| B1 | 化学提示成对图 | 0.6207 | 0.4091 | 0.3122 | 0.3333 |
| B2 | 化学提示超图 | 0.4483 | 0.3194 | 0.2329 | 0.1600 |
| F0 | 最终归一化超图 无重排 | 0.6552 | 0.4683 | 0.3842 | 0.4267 |
| F1 | 最终归一化超图 有重排 | 0.6724 | 0.4684 | 0.3873 | 0.4267 |

数据：[检索汇总](experiments/final_v1/retrieval/shared_retrieval_summary_retained.csv)、[CFR 汇总](experiments/final_v1/cfr/composite_fact_recall_retained.csv)、[审核记录](experiments/final_v1/cfr/shared_qrels_final_audit.json)。

F0/F1 共用 hybrid RRF top-50 候选池，只切换重排。F1 相比 F0 的 Hit@5 增加 1.72 个百分点，CFR 均为 64/150。因此主要改善来自最终表示与候选组织，重排提供有限的顺序优化。B1/B2 的检索入口和候选预算不同，不能作为严格的单变量结构消融；见 [B1/B2 诊断](experiments/final_v1/reports/B1_B2_retrieval_protocol_diagnosis.md)。当前没有报告统计显著性。

QA 是补充结果：F1 的 40 道题使用 `kimi-k2.6`，top-k=5、1,500 字符证据预算、temperature=1.0、top-p=0.95、seed=20260811。F1 使用阿里 DashScope，历史运行使用 Moonshot，不能声称服务条件完全一致。历史多组汇总尚不完整，F0 未运行 QA；见 [QA 协议](experiments/final_v1/qa/qa_final_protocol.json)。

## 安装与本地运行

建议 Python 3.11/3.12 和支持 Vite 5 的 Node.js。运行环境需要可用的 OpenAI 兼容 LLM 与 embedding 服务；仅查看和复算归档结果无需 API。

```powershell
git clone https://github.com/FallRain0905/Hyper-ChE.git
cd Hyper-ChE
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r web-ui/backend/requirements.txt
```

### 后端

首次启动前用自己的信息设置管理员环境变量，并生成稳定的应用密钥；凭证不写入代码或 Git。

```powershell
$env:HYPERCHE_ADMIN_EMAIL="your-admin@example.com"
$env:HYPERCHE_ADMIN_PASSWORD="replace_with_a_strong_password"
$env:JWT_SECRET=(python -c "import secrets; print(secrets.token_hex(32))")
$env:APP_SECRET_KEY=(python -c "import secrets; print(secrets.token_hex(32))")
cd web-ui/backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

缺少管理员邮箱或密码时，不自动创建管理员。已有安装重启时应使用原来的 `JWT_SECRET` 和 `APP_SECRET_KEY`。生产环境可配置 `DATABASE_URL` 使用 PostgreSQL；本地开发可以使用后端的 SQLite 回退。

### 前端

在另一个终端，从仓库根目录执行：

```powershell
cd web-ui/frontend
npm ci
$env:VITE_SERVER_URL="http://localhost:8000"
npm run start:production
```

`start:production` 连接真实后端；`npm run dev` 是原有的 mock 模式。提供商和模型在 Web 的通道/配置页面设置。知识库初始为空，上传有使用权限的文献后构建，或私下挂载已有缓存。

### Docker

```powershell
Copy-Item .env.hyperche.example .env
# 编辑 .env 中的管理员、数据库密码和应用密钥
docker compose -f docker-compose.hyperche.yml --env-file .env up -d --build
```

部署和数据持久化见 [deploy/README.md](deploy/README.md)。镜像包含源码和配置，原始文献及向量缓存需自行构建或挂载。

## 结果复现与新实验

**离线复算已发布结果，无需模型调用：**

```powershell
python scripts/reproduce_paper_metrics.py
```

该脚本用冻结候选排名、qrels 和事实支持文本块重算排序指标及 CFR，并核对本 README 对应的归档汇总。完整重建则需要原始语料、查询文件、缓存及私人服务配置。

**查看构建和检索参数：**

```powershell
python scripts/build_experiment_cache.py --help
python scripts/normalize_cache_posthoc.py --help
python scripts/build_final_cache_posthoc.py --help
python scripts/run_final_retrieval.py --help
python scripts/run_qa_formal_llm.py --help
```

`configs/experiments/modes.yaml` 定义模式开关。缓存的 `run_config.json` 才是实际运行依据；不要仅凭当前 YAML 推断历史 B0 的抽取设置。`continue_final_experiment.py` 保留为原实验续跑脚本，依赖历史 `outputs/` 文件布局，不是克隆后即可一键重建论文的入口。

最终缓存构建与评估使用独立目标目录，保持原始缓存只读。不要让多个构建进程写同一缓存。Endpoint 文件由用户本地创建，格式为每行 `base_url|api_key`，并通过 `--embedding-endpoints-file` 等参数提供；这些文件必须留在 Git 之外。

## 测试与论文图

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests
npm --prefix web-ui/frontend run build
python -m pip install -r requirements-paper.txt
python paper/figures/make_paper_figures.py
```

LaTeX 从 `paper/latex/` 编译：

```powershell
cd paper/latex
pdflatex -interaction=nonstopmode -halt-on-error hyperche_arxiv.tex
pdflatex -interaction=nonstopmode -halt-on-error hyperche_arxiv.tex
```

## 数据与贡献边界

仓库发布代码、配置示例、经审核的实验结果和论文材料。运行数据库、API key、上传文献全文、LLM 缓存、大型向量文件及临时构建输出保持本地。公开实验标注中的事实和简短支持片段用于结果核验，源文献版权属于原作者/出版方。

## License 与来源

代码沿用 [Apache-2.0](LICENSE)。HyperChE 是基于 [iMoonLab/Hyper-RAG](https://github.com/iMoonLab/Hyper-RAG) 的衍生项目，原框架及保留的示例/资源归属原作者。论文也参考了 [HyperGraphRAG](https://arxiv.org/abs/2503.21322) 的高阶知识表示与论文组织。HyperChE 论文目前是草稿，尚无可引用的正式 arXiv 编号。
