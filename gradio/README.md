# Hyper-RAG Hypergraph Visualizer - Gradio 版本

使用 **AntV G6 BubbleSets** 的超图可视化工具，**完全复刻 Web-UI 的显示效果**。

## ✨ 特性

- 🔍 **Vertex Details** - 选择顶点查看其属性和关联超边，带有右侧信息面板
- 🔷 **Full Hypergraph** - 查看完整的超图，所有顶点和超边
- **BubbleSets** - 使用与 Web-UI 完全相同的 BubbleSets 算法显示超边
- **交互式** - 支持缩放、拖拽节点、悬停查看详情

## 🔧 与 Web-UI 的一致性

本项目已完全对齐 Web-UI 的超图显示效果：

| 配置项 | Gradio 版本 | Web-UI 版本 |
|--------|-------------|--------------|
| G6 版本 | v5 (standalone) | Graphin 2.12.2 (基于 G6) ✅ |
| BubbleSets 参数 | 完全一致 ✅ | 完全一致 |
| 实体类型颜色 | 完全一致 ✅ | 完全一致 |
| 超边颜色 | 完全一致 ✅ | 完全一致 |
| Layout 配置 | force | force, clustering ✅ |
| Behaviors | zoom, drag | zoom, drag ✅ |
| Tooltip | 自定义 HTML | 自定义 HTML ✅ |

### BubbleSets 参数（完全一致）

```javascript
{
    maxRoutingIterations: 100,
    maxMarchingIterations: 20,
    pixelGroup: 4,
    edgeR0: 10,
    edgeR1: 60,
    nodeR0: 15,
    nodeR1: 50,
    morphBuffer: 10,
    threshold: 4,
    memberInfluenceFactor: 1,
    edgeInfluenceFactor: 4,
    nonMemberInfluenceFactor: -0.8,
    virtualEdges: true
}
```

### 颜色配置（完全一致）

#### 实体类型颜色
```python
ENTITY_TYPE_COLORS = {
    'PERSON': '#00C9C9',
    'CONCEPT': '#a68fff',
    'ORGANIZATION': '#F08F56',
    'LOCATION': '#16f69c',
    'EVENT': '#004ac9',
    'PRODUCT': '#f056d1',
    'DEFAULT': '#8566CC'
}
```

#### 超边颜色
```python
BUBBLE_COLORS = [
    '#F6BD16', '#00C9C9', '#F08F56', '#D580FF',
    '#FF3D00', '#16f69c', '#004ac9', '#f056d1',
    '#a680ff', '#c8ff00'
]
```

## 🚀 技术架构

### 为什么使用 G6 而不是 Graphin？

**Graphin** 是一个 React 组件库，没有独立的浏览器构建（standalone build），无法直接在纯 HTML/JavaScript 环境中使用。

**G6** 是 Graphin 的底层图形引擎，提供：
- ✅ 独立的浏览器构建（通过 CDN 加载）
- ✅ 完整的 BubbleSets 插件支持
- ✅ 与 Web-UI 完全一致的配置参数

### CDN 加载

```html
<script src="https://cdn.jsdelivr.net/npm/@antv/g6@5/dist/g6.min.js"></script>
```

使用 **jsDelivr CDN** 加载 G6 v5 独立浏览器构建。

### 数据流程

```
.hgdb 文件 (pickle)
    ↓
load_hypergraph_data()
    ↓
vertices: {v_id: {entity_type, description, ...}}
hyperedges: {key: {vertices: [], keywords: ...}}
    ↓
create_g6_options()
    ↓
G6 配置对象（包含 BubbleSets 插件）
    ↓
create_g6_html()
    ↓
gr.HTML() 渲染
```

## 📦 安装

```bash
cd gradio
pip install -r requirements.txt
```

## 🚀 运行

### Windows
双击运行 `start.bat`

### Linux/Mac
```bash
bash start.sh
```

### 或直接运行
```bash
python app.py
```

### 运行调试版本
```bash
python debug_app.py
```

## 📖 使用

1. 选择一个数据库（从 `web-ui/backend/hyperrag_cache/` 目录）
2. 选择一个顶点查看 Vertex Details
3. 或切换到 Full Hypergraph 查看完整超图

## 🐛 调试

运行 `debug_app.py` 查看详细的加载状态：
- G6 库加载状态
- Graph 实例创建状态
- Canvas 元素检查
- 完整配置选项

打开浏览器控制台 (F12) 查看详细日志。

## 📝 文件结构

```
gradio/
├── app.py          # 主应用 - 包含完整的 G6 + BubbleSets 集成
├── debug_app.py    # 调试工具 - 用于诊断显示问题
├── test.py         # HTML 渲染测试工具
├── start.bat       # Windows 启动脚本
├── start.sh        # Linux/Mac 启动脚本
├── requirements.txt # Python 依赖
└── README.md       # 本文件
```

## 📚 相关文档

- [AntV G6 官方文档](https://g6.antv.antgroup.com/)
- [G6 v5 API](https://g6.antv.antgroup.com/api)
- [BubbleSets 插件文档](https://g6.antv.antgroup.com/manual/plugin/bubble-sets)
- [G6 安装指南](https://g6.antv.antgroup.com/manual/getting-started/installation)

## 🔗 项目链接

- [Hyper-RAG 主仓库](https://github.com/iMoonLab/Hyper-RAG)
- [Web-UI 文档](../web-ui/README.md)
