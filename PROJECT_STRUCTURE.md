# 液流电池Web应用 - 核心文件清单

## 项目概述
这是一个基于Hyper-RAG的通用RAG系统，现在需要转换为液流电池专用应用。

## 核心目录结构

### 1. 后端核心 (Backend Core)
- **`hyperrag/`** - Hyper-RAG核心库
  - `hyperrag.py` - 主要RAG实现
  - `base.py` - 基础类和接口
  - `operate.py` - 操作逻辑
  - `storage.py` - 存储管理
  - `llm.py` - LLM集成
  - `prompt.py` - 提示词管理
  - `utils.py` - 工具函数

- **`web-ui/backend/`** - Web应用后端
  - `main.py` - FastAPI主应用
  - `db.py` - 数据库管理
  - `file_manager.py` - 文件管理
  - `hyperrag.py` - Hyper-RAG集成
  - `cograg.py` - Cog-RAG集成

### 2. 前端核心 (Frontend Core)
- **`web-ui/frontend/`** - React前端应用
  - `src/components/` - 可复用组件
    - `HyperGraph/` - 超图可视化组件
    - `DatabaseSelector/` - 数据库选择器
    - `RetrievalInfo/` - 检索信息展示
    - `RetrievalHyperGraph/` - 检索超图可视化
  - `src/pages/` - 页面组件
    - `Home/` - 主页/聊天界面
    - `Hyper/Graph/` - 超图数据可视化
    - `Hyper/FullGraph/` - 完整超图可视化
    - `Files/` - 文件管理
    - `Setting/` - 设置页面
  - `src/store/` - 状态管理
    - `globalUser.ts` - 全局用户状态
  - `src/hooks/` - 自定义Hooks
    - `useWebSocket.ts` - WebSocket连接
  - `src/utils/` - 工具函数
    - `index.ts` - 通用工具
  - `src/App.tsx` - 主应用组件
  - `package.json` - 前端依赖

### 3. 其他界面 (Other Interfaces)
- **`gradio/`** - Gradio界面
  - `app.py` - Gradio主应用
  - 相关配置文件

- **`streamlit/`** - Streamlit界面
  - `app.py` - Streamlit主应用
  - `lib/` - 支持库

### 4. 评估和示例 (Evaluation & Examples)
- **`evaluate/`** - 评估代码
- **`examples/`** - 示例代码

### 5. 配置和文档 (Config & Docs)
- **`requirements.txt`** - Python依赖
- **`README.md`** - 项目说明
- **`LICENSE`** - 许可证
- **`service_api.py`** - API服务
- **`.gitignore`** - Git忽略配置

## 液流电池应用定制要点

### 需要修改的核心文件：

1. **前端定制化**：
   - `web-ui/frontend/src/App.tsx` - 应用标题和品牌
   - `web-ui/frontend/src/pages/Home/index.tsx` - 聊天界面定制
   - `web-ui/frontend/src/pages/Setting/index.tsx` - 设置页面
   - `web-ui/frontend/package.json` - 应用名称和描述

2. **后端定制化**：
   - `web-ui/backend/main.py` - API端点和配置
   - `web-ui/backend/db.py` - 数据库配置
   - `requirements.txt` - 添加液流电池相关依赖

3. **提示词定制**：
   - `hyperrag/prompt.py` - 针对液流电池的提示词

### 关键技术栈：
- **前端**: React + TypeScript + Ant Design + Graphin
- **后端**: FastAPI + Python
- **RAG引擎**: Hyper-RAG + Cog-RAG
- **数据库**: HypergraphDB
- **可视化**: Graphin (超图可视化)

## 启动方式

### 前端启动：
```bash
cd web-ui/frontend
npm install
npm run dev
```

### 后端启动：
```bash
cd web-ui/backend
python main.py
```

## 注意事项

1. 该项目已经实现了完整的RAG功能，包括双系统支持（Hyper-RAG和Cog-RAG）
2. 具有完善的超图可视化功能
3. 支持文档上传、嵌入、检索等完整流程
4. 需要根据液流电池领域知识定制提示词和界面文本

## 下一步建议

1. 修改应用名称和品牌标识
2. 定制液流电池相关的提示词
3. 调整界面文案和示例
4. 添加液流电池领域的预处理和后处理逻辑
