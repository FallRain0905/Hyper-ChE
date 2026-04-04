# Hyper-RAG

<div align="center">
  <h1>Hyper-RAG</h1>
  <p><em>Combating LLM Hallucinations using Hypergraph-Driven Retrieval-Augmented Generation</em></p>
</div>

![Performance](https://img.shields.io/github/languages/top/iMoonLab/Hyper-RAG?color=purple)
![Size](https://img.shields.io/github/repo-size/iMoonLab/Hyper-RAG?color=purple)
![License](https://img.shields.io/github/license/iMoonLab/Hyper-RAG?color=purple)

---

## 概述 / Overview

**Hyper-RAG** 是一个基于超图（Hypergraph）的检索增强生成（RAG）方法，旨在减少大语言模型（LLM）的幻觉问题。

Hyper-RAG 通过以下方式增强 RAG：
- **超图建模**：能够建模超越成对关系的复杂实体关联
- **原生超图数据库**：使用 [Hypergraph-DB](https://github.com/iMoonLab/Hypergraph-DB) 作为基础
- **多层级关系**：同时捕获低阶和高阶关联
- **性能优化**：在多个数据集上超越传统 RAG 方法

### 核心特性

| 特性 | 说明 |
|------|------|
| :heavy_check_mark: **超图知识建模** | 使用超图全面建模领域特定知识中的关联，比传统图数据组织更复杂 |
| :heavy_check_mark: **原生 Hypergraph-DB 集成** | 基于 Hypergraph-DB 构建，支持快速检索高阶关联 |
| :heavy_check_mark: **卓越性能** | 在 NeurologyCorp 数据集上比直接 LLM 使用平均提升 12.3%，超越 Graph RAG 和 Light RAG |
| :heavy_check_mark: **广泛验证** | 在九个多样化数据集上比 Light RAG 提升 35.5% |
| :heavy_check_mark: **高效检索** | 轻量级变体 Hyper-RAG-Lite 检索速度提升 2 倍 |

---

## 项目结构 / Project Structure

```
Hyper-RAG/
├── hyperrag/              # 核心超图 RAG 库
├── web-ui/               # Web 界面（React + FastAPI）
├── gradio/               # Gradio 界面
├── streamlit/            # Streamlit 界面
└── reproduce/             # 论文复现代码
```

---

## 用户界面 / User Interfaces

本项目提供三种用户界面：

### 1. Web-UI (React + FastAPI)

功能完整的 Web 应用，支持超图可视化和文档处理。

**特性：**
- 完整超图可视化（Full Graph）
- 顶点详情查看（Vertex Details）
- 文档上传和处理
- 实时处理进度显示
- 支持多种 LLM 提供商

**启动方式：**

```bash
cd web-ui

# 方式 1: 直接启动（开发环境）
npm install                # 安装前端依赖
pip install -r requirements.txt
python main.py             # 启动后端
# 前端访问 http://localhost:3000
# 后端访问 http://localhost:8000

# 方式 2: Docker 部署
docker-compose up
# 访问 http://localhost:5000
```

**详细文档：** [Web-UI README](web-ui/README.md)

---

### 2. Gradio

轻量级 Web 界面，使用 AntV G6 进行超图可视化，支持文档嵌入处理。

**特性：**
- 超图视图（G6 + BubbleSets）
- 顶点详情视图
- 文档模式 - 使用真实 HyperRAG LLM 进行实体提取
- 支持文档分块、实体提取、超边构建

**启动方式：**

```bash
cd gradio

# 配置 LLM API（在 settings.json 中设置 API Key）
# 或运行后按界面提示配置

pip install -r requirements.txt
python app.py
# 访问 http://localhost:7860
```

**配置文件示例 (settings.json)：**

```json
{
  "apiKey": "your-api-key-here",
  "modelProvider": "openai",
  "modelName": "gpt-4o-mini",
  "baseUrl": "https://api.openai.com/v1",
  "embeddingModel": "text-embedding-3-small",
  "embeddingDim": 1536,
  "maxTokens": 2000,
  "temperature": 0.7
}
```

---

### 3. Streamlit

基于 Streamlit 的界面，提供交互式超图查询和可视化。

**启动方式：**

```bash
cd streamlit

pip install -r requirements.txt
streamlit run app.py
```

---

## 安装 / Installation

### 环境要求

- Python 3.8+
- Node.js 18+ (仅 Web-UI)
- Docker & Docker Compose (可选，用于部署)

### 标准安装

```bash
# 克隆项目
git clone https://github.com/iMoonLab/Hyper-RAG.git
cd Hyper-RAG

# 安装依赖
pip install -r requirements.txt
```

### Docker 安装

```bash
# 使用 Docker Compose 启动
cd web-ui
docker-compose up

# 或手动构建并运行
docker build -t hyper-rag .
docker run -p 5000:5000 hyper-rag
```

---

## 快速开始 / Quick Start

### 1. 配置 LLM API

编辑或创建 `my_config.py` 文件：

```python
LLM_BASE_URL = "your-llm-url"      # 例如: https://api.openai.com/v1
LLM_API_KEY = "your-api-key"
LLM_MODEL = "gpt-4o-mini"         # 或其他支持的模型

EMB_BASE_URL = "your-embedding-url"
EMB_API_KEY = "your-api-key"
EMB_MODEL = "text-embedding-3-small"
EMB_DIM = 1536                     # 嵌入维度
```

### 2. 运行 Demo

```bash
# 运行示例
python examples/hyperrag_demo.py

# 或按步骤运行完整流程
# 1. 预处理数据
python reproduce/Step_0.py

# 2. 构建超图
python reproduce/Step_1.py

# 3. 提取问题
python reproduce/Step_2_extract_question.py

# 4. 回答问题
python reproduce/Step_3_response_question.py
```

### 3. 查询模式

支持多种查询模式：

```python
from hyperrag import HyperRAG, QueryParam

# 初始化 HyperRAG
rag = HyperRAG(
    working_dir="./cache",
    llm_model_func=your_llm_func,
    embedding_func=your_embedding_func
)

# 插入文档
rag.ainsert("你的文档内容...")

# 查询
param = QueryParam(
    mode="hyper",              # hyper, hyper-lite, naive, graph, llm
    top_k=60,
    max_token_for_text_unit=1600,
    max_token_for_entity_context=300,
    max_token_for_relation_context=1600,
    response_type="Multiple Paragraphs"
)

result = rag.aquery("你的问题...", param)
```

**查询模式说明：**

| 模式 | 说明 |
|------|------|
| `hyper` | 完整超图模式，使用实体和超边检索 |
| `hyper-lite` | 轻量级模式，仅使用实体检索 |
| `naive` | 朴素 RAG，直接检索文本块 |
| `graph` | 图模式，二元关系检索 |
| `llm` | 纯 LLM，不检索 |

---

## 评估 / Evaluation

本项目提供两种评估方法：

### Scoring-based 评估

基于评分的评估方法，允许对多个模型输出进行量化比较。

```bash
python evaluate/evaluate_by_scoring.py
```

### Selection-based 评估

基于选择的评估方法，适用于预选候选模型的场景。

```bash
python evaluate/evaluate_by_selection.py
```

---

## 性能基准 / Benchmarks

| 数据集 | Hyper-RAG | Graph RAG | Light RAG | Direct LLM |
|----------|------------|------------|------------|-------------|
| NeurologyCorp | +12.3% | - | - | - |

**详细评估结果请参考论文：** [arXiv:2504.08758](https://arxiv.org/abs/2504.08758)

---

## 贡献 / Contributing

欢迎贡献！如果你想贡献代码，请遵循以下步骤：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 许可证 / License

本项目采用 Apache 2.0 许可证 - 详见 [LICENSE](LICENSE) 文件。

---

## 致谢 / Acknowledgments

- 感谢 [LightRAG](https://github.com/HKUDS/LightRAG) 和 [Hypergraph-DB](https://github.com/iMoonLab/Hypergraph-DB) 项目，为 Hyper-RAG 的实现提供了基础

---

## 引用 / Citation

如果您在研究中使用了 Hyper-RAG，请使用以下格式引用：

```bibtex
@misc{feng2025hyperrag,
  title={Hyper-RAG: Combating LLM Hallucinations using Hypergraph-Driven Retrieval-Augmented Generation},
  author={Yifan Feng and Hao Hu and Xingliang Hou and Shiquan Liu and Shihui Ying and Shaoyi Du and Han Hu and Yue Gao},
  year={2025},
  eprint={2504.08758},
  archivePrefix={arXiv},
  primaryClass={cs.IR},
  url={https://arxiv.org/abs/2504.08758}
}
```

---

## 联系方式 / Contact

- **团队**: iMoon Lab, Tsinghua University
- **Email**: [evanfeng97@gmail.com](mailto:evanfeng97@gmail.com)
- **GitHub**: [iMoonLab/Hyper-RAG](https://github.com/iMoonLab/Hyper-RAG)

---

<div align="center">
  <sub>如有问题，欢迎提交 Issue 或联系作者</sub>
</div>
