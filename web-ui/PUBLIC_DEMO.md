# 公开液流电池实例

公开体验使用 `/#/try`，项目汇报使用 `/report/hyperche-demo.html`。模型尚未配置时，可以查看真正的本地缓存超图及汇报，页面明确区分离线案例与本轮检索结果。

## 最终检索与缓存

生产部署将私下传输的已验证最终缓存只读挂载到 `/app/readonly_caches/final_v1`，并通过 `HYPERCHE_FINAL_CACHE_DATABASE=case1` 保持示例名兼容。缓存不进入 Git、镜像或公共下载目录。普通旧实例仍支持原有缓存检查，Git LFS 指针会判为不可用。

最终实例执行实体/超边 dense 与 BM25、RRF、关联扩展、固定 top-50 超边池、确定性重排及来源局部证据重构，默认 top-5 证据。查询 embedding 必须为 `Qwen/Qwen3-Embedding-4B`、2560 维，渠道由管理员配置。此次不升级新上传文献的建库流程。

## 接口

- `GET /public/demo/status`：分别返回 `cache_ready`、`models_ready` 与整体 `ready`。
- `GET /public/demo/graph`：无模型调用的真实缓存局部图，明确标记离线。
- `POST /public/demo/query`：同步答案、同轮图与来源、`retrieval_meta`。
- `POST /public/demo/query/stream`：依次发送 `meta`、`retrieval`、`token`、`done`，失败发送 `error`；流结束后不再次检索，半途失败不自动重复生成。

匿名查询使用 Redis 原子限额与并发租约：每 IP 每分钟 2 次、每天 20 次，全站每天 100 次；并发每 IP 1、全站 2。Redis 不可用时停止公开模型调用。

线上生成记录为 Web 运行配置，不等同于冻结论文 QA。历史参数名称中的 1500 实际按整个上下文的空白分词单位计算，并非 1500 字符；返回元数据如实记录这一点。

完整部署、私有管理员信息、持久化与回滚见 [部署说明](../deploy/README.md)。
