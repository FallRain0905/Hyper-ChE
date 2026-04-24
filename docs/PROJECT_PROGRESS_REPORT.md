# Hyper-RAG 项目进度汇报文档

## 项目概述

**Hyper-RAG** 是一个基于超图（Hypergraph）的检索增强生成（RAG）系统，核心创新在于使用超图建模实体间的高阶关系，相比传统图方法能更准确地捕获多实体关联。

---

## 一、系统架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web UI Layer                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   React 前端     │  │   TypeScript    │  │   Ant Design    │ │
│  │  - 文件管理      │  │  - 状态管理      │  │  - 超图可视化   │ │
│  │  - 数据库选择    │  │  - WebSocket    │  │  - Graphin     │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend API Layer                           │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    FastAPI (main.py)                        ││
│  │  - 文件上传/嵌入接口                                         ││
│  │  - 数据库管理端点                                            ││
│  │  - WebSocket 实时进度推送                                    ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       RAG Core Layer                             │
│  ┌───────────────────┐  ┌───────────────────┐                   │
│  │    HyperRAG       │  │     Cog-RAG       │                   │
│  │  (超图检索)        │  │   (主题检索)      │                   │
│  └───────────────────┘  └───────────────────┘                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   领域适配层 (Domains)                       ││
│  │  ┌───────────┐  ┌───────────────┐  ┌───────────────────┐   ││
│  │  │  default  │  │ flow_battery  │  │  (可扩展新领域)   │   ││
│  │  │ 通用领域   │  │ 液流电池领域   │  │                   │   ││
│  │  └───────────┘  └───────────────┘  └───────────────────┘   ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage Layer                               │
│  ┌───────────────────┐  ┌───────────────────┐                   │
│  │  HypergraphDB     │  │   NanoVectorDB    │                   │
│  │  (超图存储)        │  │   (向量存储)      │                   │
│  └───────────────────┘  └───────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心目录结构

```
Hyper-RAG/
├── hyperrag/                    # 核心RAG库
│   ├── hyperrag.py             # 主入口类 HyperRAG
│   ├── operate.py              # 核心操作逻辑（实体提取、合并、查询）
│   ├── prompt.py               # 提示词管理（支持多领域）
│   ├── storage.py              # 存储层实现
│   ├── llm.py                  # LLM调用封装
│   ├── domains/                # ⭐ 领域适配模块（我们开发）
│   │   ├── domain_manager.py   # 领域管理器
│   │   ├── validator.py        # 输出验证器
│   │   ├── default/            # 默认领域
│   │   └── flow_battery/       # 液流电池领域
│   └── utils.py                # 工具函数
│
├── cog-rag/                     # Cog-RAG模块（主题级检索）
│   └── cograg/
│       ├── cograg.py           # 主入口类
│       ├── operate.py          # 操作逻辑
│       └── ...
│
└── web-ui/                      # Web界面
    ├── backend/
    │   ├── main.py             # FastAPI后端
    │   ├── db.py               # 数据库管理
    │   ├── file_manager.py     # 文件管理（支持指定数据库）
    │   └── hyperdb/            # 超图数据库封装
    └── frontend/
        └── src/
            └── pages/Files/    # 文件管理页面（数据库选择功能）
```

---

## 二、文档嵌入流程（核心流程）

### 2.1 完整嵌入流水线

```
┌─────────────────────────────────────────────────────────────────────┐
│                        文档嵌入流水线                                │
└─────────────────────────────────────────────────────────────────────┘

文档上传
    │
    ▼
┌───────────────┐
│  文档分块      │  chunking_by_token_size()
│  (Token窗口)   │  - chunk_token_size: 1200
│               │  - overlap: 100 tokens
└───────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│                  并行处理每个 Chunk                                │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │               Step 1: 实体提取 (LLM)                         │ │
│  │  输入: chunk_text                                           │ │
│  │  输出: JSON格式的实体列表                                    │ │
│  │        {"name": "VO²⁺", "type": "ACTIVE_SPECIES", ...}      │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            │                                      │
│                            ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │               Step 2: 低阶关系提取 (LLM)                     │ │
│  │  输入: 实体列表 + chunk_text                                │ │
│  │  输出: 二元关系（超边）                                      │ │
│  │        {"source": "VO²⁺", "target": "Nafion 117", ...}      │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            │                                      │
│                            ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │               Step 3: 高阶关系提取 (LLM)                     │ │
│  │  输入: 实体列表 + chunk_text                                │ │
│  │  输出: 多元关系（超边）                                      │ │
│  │        {"vertices": ["VO²⁺", "Nafion", "80mA/cm²"], ...}    │ │
│  └─────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│                       实体合并 (关键步骤)                          │
│  _merge_nodes_then_upsert()                                       │
│  - 同名实体的描述累积合并                                          │
│  - 来源ID追踪                                                      │
│  - LLM摘要（描述过长时）                                           │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│                       存储到超图数据库                             │
│  HypergraphStorage.upsert_vertex()                                │
│  HypergraphStorage.upsert_hyperedge()                             │
│  NanoVectorDB.upsert() (实体向量)                                  │
└───────────────────────────────────────────────────────────────────┘
```

### 2.2 核心代码入口

**文件**: `hyperrag/hyperrag.py`

```python
async def ainsert(self, string_or_strings):
    # 1. 文档分块
    inserting_chunks = {}
    for doc_key, doc in new_docs.items():
        chunks = {
            compute_mdhash_id(dp["content"], prefix="chunk-"): {
                **dp,
                "full_doc_id": doc_key,
            }
            for dp in chunking_by_token_size(
                doc["content"],
                overlap_token_size=self.chunk_overlap_token_size,
                max_token_size=self.chunk_token_size,
            )
        }

    # 2. 实体提取（核心）
    maybe_new_kg = await extract_entities(
        inserting_chunks,
        knowledge_hypergraph_inst=self.chunk_entity_relation_hypergraph,
        entity_vdb=self.entities_vdb,
        relationships_vdb=self.relationships_vdb,
        global_config=asdict(self),
    )
```

### 2.3 实体合并机制（术语统一的关键）

**文件**: `hyperrag/operate.py` - `_merge_nodes_then_upsert()`

```python
async def _merge_nodes_then_upsert(
    entity_name: str,
    nodes_data: list[dict],
    knowledge_hypergraph_inst,
    global_config: dict,
):
    # 1. 检查是否已存在同名实体
    already_node = await knowledge_hypergraph_inst.get_vertex(entity_name)

    if already_node is not None:
        # 2. 读取已有信息
        already_description.append(already_node["description"])
        already_additional_properties.append(already_node["additional_properties"])

    # 3. 合并所有描述（使用分隔符）
    description = GRAPH_FIELD_SEP.join(
        sorted(set([dp["description"] for dp in nodes_data] + already_description))
    )

    # 4. 如果描述过长，调用LLM进行摘要
    description = await _handle_entity_summary(
        entity_name, description, global_config
    )

    # 5. 更新超图中的顶点（同名实体会被覆盖，描述被合并）
    await knowledge_hypergraph_inst.upsert_vertex(entity_name, node_data)
```

**关键点**:
- 同一数据库内，同名实体会自动合并描述
- 来源ID会被累积记录，可追溯
- 这就是"术语统一"的核心机制

---

## 三、领域适配模块（我们开发的核心功能）

### 3.1 模块架构

```
hyperrag/domains/
├── __init__.py
├── domain_manager.py     # 领域管理器（加载配置、缓存）
├── validator.py          # 输出验证器（验证实体/关系字段）
│
├── default/              # 默认领域（通用）
│   ├── config.json
│   └── entity_extraction.txt
│
└── flow_battery/         # ⭐ 液流电池领域（定制）
    ├── config.json               # 领域本体配置
    ├── entity_extraction.txt     # 实体提取提示词
    ├── low_order_extraction.txt  # 低阶关系提取提示词
    ├── high_order_extraction.txt # 高阶关系提取提示词
    └── query_keywords.txt        # 查询关键词提取提示词
```

### 3.2 液流电池领域本体设计

**文件**: `hyperrag/domains/flow_battery/config.json`

```json
{
  "domain_name": "flow_battery",
  "domain_description": "液流电池（Redox Flow Battery）研究领域",

  "entity_types": [
    {"name": "ACTIVE_SPECIES", "description": "氧化还原活性物质"},
    {"name": "MEMBRANE", "description": "离子交换膜"},
    {"name": "ELECTRODE", "description": "电极材料"},
    {"name": "CONDITION", "description": "实验条件", "subtypes": ["operating", "processing"]},
    {"name": "METRIC", "description": "性能指标", "subtypes": ["performance", "material_property"]},
    {"name": "DEGRADATION", "description": "退化机制"},
    {"name": "SYSTEM", "description": "系统/装置"}
  ],

  "relation_types": [
    {"name": "COMPOSITION", "description": "组成/制备关系"},
    {"name": "OPERATION", "description": "操作条件关系"},
    {"name": "DEGRADATION", "description": "退化/失效关系"},
    {"name": "COMPARISON", "description": "对比关系"}
  ],

  "output_format": "json",
  "language": "English"
}
```

### 3.3 领域管理器核心代码

**文件**: `hyperrag/domains/domain_manager.py`

```python
class DomainManager:
    def __init__(self):
        self._domains_dir = Path(__file__).parent
        self._config_cache: Dict[str, dict] = {}

    def get_available_domains(self) -> List[str]:
        """获取所有可用领域"""
        domains = []
        for item in self._domains_dir.iterdir():
            if item.is_dir() and (item / "config.json").exists():
                domains.append(item.name)
        return domains

    def load_domain_config(self, domain_name: str) -> dict:
        """加载领域配置"""
        if domain_name in self._config_cache:
            return self._config_cache[domain_name]

        config_path = self._domains_dir / domain_name / "config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self._config_cache[domain_name] = config
        return config

    def get_entity_types(self, domain_name: str) -> List[str]:
        """获取领域的实体类型列表"""
        config = self.load_domain_config(domain_name)
        return [e["name"] for e in config.get("entity_types", [])]
```

### 3.4 提示词生成流程

**文件**: `hyperrag/prompt.py`

```python
def get_entity_extraction_prompt(domain: str = 'default', **kwargs) -> str:
    """生成实体提取提示词"""
    if domain == 'default':
        # 使用默认的分隔符格式
        return PROMPTS["entity_extraction"].format(**kwargs)

    # 使用领域特定的模板
    template = domain_manager.get_prompt_template(domain, "entity_extraction")
    return template.format(**kwargs)
```

### 3.5 JSON格式处理流程

**文件**: `hyperrag/operate.py` - `_process_json_format_extraction()`

```python
async def _process_json_format_extraction(
    content: str,
    chunk_key: str,
    use_llm_func: callable,
    global_config: dict,
    domain: str = 'default'
) -> tuple[list, list]:
    """处理JSON格式的领域特定提取"""

    # Step 1: 实体提取
    entity_prompt = get_entity_extraction_prompt(
        domain=domain,
        CHUNK_TEXT=content
    )
    entity_result = await use_llm_func(entity_prompt)
    entities_json = parse_json_entities(entity_result, chunk_key)

    # 转换为标准格式
    entities = [convert_json_entity_to_standard_format(e, chunk_key)
                for e in entities_json]

    # Step 2: 低阶关系提取
    entity_info = [{"name": e["name"], "type": e["type"], ...}
                   for e in entities_json]
    low_prompt = get_low_order_extraction_prompt(
        domain=domain,
        K_v_JSON=json.dumps(entity_info),
        CHUNK_TEXT=content
    )
    low_result = await use_llm_func(low_prompt)
    low_relations_json = parse_json_relations(low_result, chunk_key)

    # Step 3: 高阶关系提取
    high_prompt = get_high_order_extraction_prompt(...)
    high_result = await use_llm_func(high_prompt)
    high_relations_json = parse_json_hyperedges(high_result, chunk_key)

    return entities, low_relations_json + high_relations_json
```

---

## 四、数据库选择功能（最近实现）

### 4.1 功能说明

允许用户在上传和嵌入时选择目标数据库：
- **自动模式**：使用文件名作为数据库名（默认）
- **已有数据库**：选择现已存在的数据库
- **新建数据库**：输入新数据库名称

### 4.2 后端接口修改

**文件**: `web-ui/backend/file_manager.py`

```python
async def save_uploaded_file(
    self,
    file_content: bytes,
    original_filename: str,
    target_database: str = None  # 新增：目标数据库
) -> Dict:
    # 如果指定了目标数据库则使用，否则使用文件名
    if target_database:
        database_name = self.sanitize_database_name(target_database)
    else:
        database_name = self.generate_database_name(original_filename)
```

**文件**: `web-ui/backend/main.py`

```python
class FileEmbedRequest(BaseModel):
    file_ids: List[str]
    target_database: Optional[str] = None  # 目标数据库
    update_file_database: bool = False     # 是否更新文件关联
```

### 4.3 使用场景

```
场景：比较不同领域提示词的效果

1. 上传文档A → 选择"新建数据库: flow_battery_default"
2. 设置领域为 default → 嵌入文档A

3. 上传文档A → 选择"新建数据库: flow_battery_custom"
4. 设置领域为 flow_battery → 嵌入文档A

5. 对比两个数据库的实体提取质量
```

---

## 五、当前进度总结

### 5.1 已完成功能

| 功能模块 | 状态 | 说明 |
|---------|------|------|
| 核心RAG引擎 | ✅ 完成 | HyperRAG + Cog-RAG 双系统 |
| Web界面 | ✅ 完成 | 文件管理、超图可视化、实时进度 |
| 领域适配框架 | ✅ 完成 | domain_manager, validator |
| 液流电池领域 | ✅ 完成 | 本体设计、4个提示词模板 |
| 数据库选择功能 | ✅ 完成 | 上传/嵌入时可指定目标数据库 |
| 实体合并机制 | ✅ 完成 | 同名实体自动合并描述 |

### 5.2 液流电池领域设计亮点

1. **7种实体类型**：覆盖RFB研究的核心概念
2. **结构化数值处理**：CONDITION/METRIC实体支持value/unit分离
3. **关系类型化**：4种语义明确的关系类型
4. **JSON输出**：结构化输出便于后处理
5. **领域验证**：自动验证实体/关系字段完整性

### 5.3 后续计划

1. **实际LLM测试**：验证液流电池提示词的提取质量
2. **性能优化**：大量文档并行处理的效率
3. **领域扩展**：可添加其他科学领域配置
4. **评估框架**：建立RAG系统的量化评估流程

---

## 六、代码调用示例

### 6.1 Python API使用

```python
from hyperrag import HyperRAG, QueryParam
from hyperrag.prompt import set_domain

# 设置领域
set_domain("flow_battery")

# 初始化
rag = HyperRAG(
    working_dir="./cache",
    llm_model_func=your_llm_func,
    embedding_func=your_embedding_func,
    domain="flow_battery"  # 指定领域
)

# 插入文档
await rag.ainsert("你的液流电池论文内容...")

# 查询
result = await rag.aquery("温度对钒液流电池效率的影响？", QueryParam(mode="hyper"))
```

### 6.2 Web API使用

```bash
# 上传文档到指定数据库
curl -X POST http://localhost:8000/files/upload \
  -F "files=@paper.pdf" \
  -F "target_database=flow_battery_research"

# 嵌入文档到指定数据库
curl -X POST http://localhost:8000/files/embed-with-progress \
  -H "Content-Type: application/json" \
  -d '{
    "file_ids": ["xxx"],
    "target_database": "flow_battery_research",
    "update_file_database": true
  }'
```

---

## 七、关键文件清单

| 文件路径 | 功能说明 | 代码行数 |
|---------|---------|---------|
| `hyperrag/hyperrag.py` | 主入口类 | ~300行 |
| `hyperrag/operate.py` | 核心操作逻辑 | ~1100行 |
| `hyperrag/prompt.py` | 提示词管理 | ~400行 |
| `hyperrag/domains/domain_manager.py` | 领域管理器 | ~250行 |
| `hyperrag/domains/validator.py` | 输出验证器 | ~250行 |
| `hyperrag/domains/flow_battery/config.json` | 液流电池本体 | ~200行 |
| `hyperrag/domains/flow_battery/*.txt` | 提示词模板 | ~200行 |
| `web-ui/backend/main.py` | FastAPI后端 | ~2300行 |
| `web-ui/backend/file_manager.py` | 文件管理 | ~200行 |
| `web-ui/frontend/src/pages/Files/index.tsx` | 文件管理页面 | ~1250行 |

---

*文档生成时间: 2026-04-23*
*项目版本: 基于最新main分支*
