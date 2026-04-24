# Hyper-RAG 项目进度汇报（演示版）

## 一、项目简介

**Hyper-RAG**：基于超图的检索增强生成系统
- 核心创新：使用超图建模多实体高阶关系
- 目标：减少LLM幻觉，提高检索准确性

---

## 二、我们完成的核心工作

### 2.1 领域适配框架

**问题**：原系统只支持通用领域，无法针对液流电池专业领域提取结构化知识

**解决方案**：设计了可扩展的领域适配模块

```
hyperrag/domains/
├── default/          # 通用领域（原版）
└── flow_battery/     # 液流电池领域（我们设计）
    ├── config.json               # 定义领域本体
    ├── entity_extraction.txt     # 实体提取prompt
    ├── low_order_extraction.txt  # 二元关系prompt
    ├── high_order_extraction.txt # 高阶关系prompt
    └── query_keywords.txt        # 查询关键词prompt
```

### 2.2 液流电池领域本体

| 实体类型 | 说明 | 示例 |
|---------|------|------|
| ACTIVE_SPECIES | 活性物质 | VO²⁺, H₂SO₄ |
| MEMBRANE | 离子交换膜 | Nafion 117 |
| ELECTRODE | 电极材料 | graphite felt |
| CONDITION | 实验条件 | temperature, current density |
| METRIC | 性能指标 | CE, VE, EE |
| DEGRADATION | 退化机制 | crossover, capacity fade |
| SYSTEM | 系统装置 | stack unit, pump |

### 2.3 文档嵌入流程改进

**原版流程**：
```
文档 → 分块 → 单一实体提取 → 写入数据库
```

**我们的改进**：
```
文档 → 分块 → 三阶段流水线（实体→低阶关系→高阶关系）
                ↓
            JSON结构化输出 → 领域验证 → 写入超图
```

### 2.4 数据库选择功能

**新增能力**：
- 上传时可指定目标数据库
- 嵌入时可选已有数据库或新建数据库
- 便于对比不同领域提示词的效果

---

## 三、关键代码位置

| 功能 | 文件 | 关键函数 |
|-----|------|---------|
| 文档嵌入入口 | `hyperrag/hyperrag.py` | `ainsert()` |
| 实体提取 | `hyperrag/operate.py` | `extract_entities()` |
| JSON处理 | `hyperrag/operate.py` | `_process_json_format_extraction()` |
| 实体合并 | `hyperrag/operate.py` | `_merge_nodes_then_upsert()` |
| 领域管理 | `domains/domain_manager.py` | `DomainManager` |
| 输出验证 | `domains/validator.py` | `DomainValidator` |

---

## 四、演示：术语统一效果

**场景**：多篇液流电池论文同时嵌入

```
论文A 提取: "VO²⁺" - "钒离子，正极活性物质"
论文B 提取: "VO²⁺" - "四价钒离子，电解液中氧化态"

合并结果:
┌─────────────────────────────────────────┐
│ 实体名: VO²⁺                            │
│ 类型: ACTIVE_SPECIES                    │
│ 描述: 钒离子，正极活性物质 | 四价钒离子  │
│       电解液中氧化态                     │
│ 来源: paper_a.pdf, paper_b.pdf          │
└─────────────────────────────────────────┘
```

---

## 五、后续计划

1. **实际测试**：用真实液流电池论文测试提取质量
2. **性能优化**：大批量文档并行处理
3. **评估框架**：建立量化评估指标

---

## 六、项目结构图

```
Hyper-RAG/
├── hyperrag/              # 核心库
│   ├── domains/           # ⭐ 领域模块（我们开发）
│   │   └── flow_battery/  # 液流电池领域
│   ├── operate.py         # 嵌入逻辑
│   └── prompt.py          # 提示词管理
│
├── cog-rag/               # Cog-RAG模块
├── web-ui/                # Web界面
│   ├── backend/           # FastAPI后端
│   └── frontend/          # React前端
│
└── docs/                  # 文档
    └── PROJECT_PROGRESS_REPORT.md  # 详细技术文档
```

---

*汇报日期: 2026-04-23*
