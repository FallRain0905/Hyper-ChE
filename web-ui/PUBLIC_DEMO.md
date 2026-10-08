# 单一公开实例：液流电池

Web UI 只保留一个公开实例，避免首页、路由和后端分别维护多套示例。

## 代码入口

- 前端实例配置：`frontend/src/config/publicDemo.ts`
- 前端交互页面：`frontend/src/pages/Landing/TryDemo.tsx`
- 前端规范路由：`/try`
- 旧液流电池路由：`/demo/flow-battery`（重定向到 `/try`）
- 旧 PFAS 路由：`/demo/pfas`（重定向到 `/try`，不再维护第二实例）
- 后端实例配置与缓存检查：`backend/public_demo.py`
- 后端状态接口：`GET /public/demo/status`
- 后端查询接口：`POST /public/demo/query`、`POST /public/demo/query/stream`

## 缓存

唯一实例使用数据库目录 `case1`：

```text
web-ui/backend/hyperrag_cache/case1
```

缓存文件由 Git LFS 管理。仓库根目录执行：

```powershell
git lfs install
git lfs pull --include="web-ui/backend/hyperrag_cache/case1/**"
```

至少需要以下文件：

```text
hypergraph_chunk_entity_relation.hgdb
kv_store_full_docs.json
kv_store_text_chunks.json
vdb_chunks.json
vdb_entities.json
vdb_relationships.json
```

`kv_store_llm_response_cache.json` 是可选的响应缓存。若文件仍是约 130 字节的 Git LFS pointer，状态接口会将其列入 `lfs_pointer_files`，不会把该实例误判为可用。

## 示例对话入口

示例问题集中存放在 `frontend/src/config/publicDemo.ts` 的 `suggestedQuestions` 中。当前包含膜、电极、铁铬体系、不同液流电池路线及 CE/VE/EE 指标解释等六个问题。

页面不内置伪造的静态答案；用户选择示例问题后，答案由唯一的 `case1` 缓存实时检索生成。
