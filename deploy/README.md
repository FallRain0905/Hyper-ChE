# HyperChE 部署

生产入口为 `https://hyperche.fallrain0905.top`，汇报入口为
`https://hyperche.fallrain0905.top/report/hyperche-demo.html`。部署到已有业务的
服务器时，使用独立 Compose 项目 `hyperche`；容器网关只监听
`127.0.0.1:8088`，由宿主 Nginx 转发。现有中转服务及其站点配置保持独立。

## 1. 私有配置与最终缓存

从 GitHub 克隆代码，将私有内容放在 checkout 之外：

```text
/opt/hyperche/releases/<commit>/        已提交的代码
/opt/hyperche/shared/.env               私有配置，权限 0600
/opt/hyperche/shared/final_cache/        经验证的最终缓存，只读挂载
/opt/hyperche/backups/                  数据与部署备份
```

复制 `.env.hyperche.example` 到私有 `.env`，填入随机数据库密码、管理员密码、
`JWT_SECRET`、`APP_SECRET_KEY`。不要将服务器登录密码或模型 API key 放入
仓库。初始管理员邮箱为 `admin@hyperche.fallrain0905.top`，管理员密码每次
新安装单独生成；更改 bootstrap 环境变量不会重设已有用户密码。

既有安装必须保留 `JWT_SECRET` 和 `APP_SECRET_KEY`，后者用于通道凭证加密。
模型与密钥池在管理员界面配置，未配置时只提供页面、缓存查看与汇报演示，
不会声称已生成真实模型答案。公开示例需同时满足 `cache_ready` 和
`models_ready` 才是 `ready`。

最终缓存由私下传输提供，不经 Git/Git LFS。挂载对应关系为：

```text
/opt/hyperche/shared/final_cache -> /app/readonly_caches/final_v1:ro
```

`HYPERCHE_FINAL_CACHE_DIR` 指向该容器路径，
`HYPERCHE_FINAL_CACHE_DATABASE=case1` 将现有公开示例名映射到最终缓存。
返回数据中的 `normalization_version=final-posthoc-v1` 标明实际版本，不能仅凭 `case1`
名称判断使用的历史缓存。完整缓存至少包括：

- `hypergraph_chunk_entity_relation.hgdb`
- `kv_store_full_docs.json`、`kv_store_text_chunks.json`
- `vdb_chunks.json`、`vdb_entities.json`、`vdb_relationships.json`
- 与最终检索一致的 `run_config.json` 及归一化映射、来源元数据等伴随文件

部署前验证文件哈希、非 LFS 指针、实体/文本块对应关系与模型维度。
旧模型路线为 `Qwen/Qwen3-Embedding-4B`、2,560 维；通道必须匹配该缓存。
原始实验缓存保持只读，公开演示不得重建、修复或追加写入它。
Compose 禁止自动创建缺失种子目录，路径错误会直接阻止启动。

## 2. 启动独立容器项目

服务器要求 Linux x86_64、Docker Engine 与支持 `--wait` 的 Compose。
确认宿主端口 8088 空闲后，在已提交且工作区干净的 release 中运行：

```bash
sh deploy/apply-release.sh /opt/hyperche/shared/.env
```

脚本静态检查 Compose、构建带 commit SHA 标签的应用镜像，然后等待健康
状态。它不操作其他 Compose 项目，也不安装/修改宿主 Nginx。
首次构建需要访问 Python/Node 镜像和依赖源；不包含原始文献或缓存镜像层。

内部端口为后端 8000、前端 5000、PostgreSQL 5432、Redis 6379，均不向
宿主公开。只允许宿主网关访问 8088；80/443 继续由原宿主 Nginx 管理。

公开查询默认按真实 IP 限制为 2 次/分钟、20 次/天，全站 100 次/天，
单 IP 并发 1、全站并发 2；计数与租约保存在 Redis。宿主网关替换外来
`X-Real-IP` / `X-Forwarded-For`，应用只信任已配置的代理网段。
`HYPERCHE_TRUSTED_PROXY_CIDRS` 可按实际 Docker 子网进一步收紧。
Redis 不可用时公开模型调用不得绕过额度检查。

## 3. 域名与 HTTPS

将 `hyperche.fallrain0905.top` 的 A 记录指向部署服务器 `154.219.99.75`。
DNS 生效后，用独立 HTTP 站点完成 ACME 验证：

```bash
sh deploy/install-host-nginx.sh http
certbot certonly --webroot -w /var/www/hyperche-acme \
  -d hyperche.fallrain0905.top --deploy-hook "systemctl reload nginx"
sh deploy/install-host-nginx.sh https
```

安装脚本仅写 `hyperche.fallrain0905.top.conf`，不编辑现有 API 站点。
它先检查 Nginx 配置，再 reload；验证失败恢复 HyperChE 原配置。
HTTPS 模板使用证书目录 `/etc/letsencrypt/live/hyperche.fallrain0905.top/`，
保留 ACME 路径并将其余 HTTP 请求重定向到 HTTPS。

两个代理层均关闭 SSE 缓冲、允许 WebSocket Upgrade，并保留源 HTTPS
协议到后端。生产 `COOKIE_SECURE=true`；`CORS_ORIGINS` 为精确 HTTPS
入口，不使用通配来源。HTTP 引导阶段不用于管理员登录或模型通道配置。
Uvicorn 的 `FORWARDED_ALLOW_IPS` 与应用的可信代理 CIDR 保持一致，使
ASGI 请求也识别原始 HTTPS/WSS 协议；不使用信任所有来源的 `*`。

## 4. 持久化与升级

命名卷保存 PostgreSQL 用户/通道/额度、Redis 计数、上传文献与文件元数据、
可写用户缓存、知识库元数据、提示词物化目录、运行日志与配置。
`docker compose down` 保留这些卷；禁止对已有安装运行 `down -v`。

升级前备份 PostgreSQL（`pg_dump`）、命名卷、私有 `.env`、只读缓存校验
清单和 HyperChE Nginx 配置，记录当前 commit 与镜像标签。发布新 release
后仍使用 `-p hyperche` 和同一私有环境文件，卷名因此保持稳定。
不要删除旧镜像或运行全局 Docker prune。

失败时先回到旧 release 目录，再恢复已有镜像：

```bash
sh deploy/rollback-release.sh PREVIOUS_COMMIT_SHA /opt/hyperche/shared/.env
```

脚本不重建镜像、不移除数据卷。若发布包含不可逆数据迁移，需额外从
备份恢复数据库；应用镜像回退不能代替数据恢复。

## 5. 上线验收

- Compose 五个服务启动，PostgreSQL、Redis、后端、前端健康。
- 仅 127.0.0.1:8088 新增监听；原中转入口和容器仍正常。
- HTTPS 首页、登录、知识库列表、Graphin/G6 超图节点与超边、字体正常。
- `/api/public/demo/status` 明确缓存版本、缓存与模型就绪状态。
- 已配置通道后，真实检索返回最终缓存证据、来源、排序及实际执行流程；
  SSE 逐段输出、WebSocket 构建进度可用。
- 公开超额请求返回限流状态，伪造转发头不能切换客户端配额。
- `/report/hyperche-demo.html` 及其中 Word 下载、离线超图演示可用。
- 重建应用容器后，用户、通道、知识库、提示包及缓存仍在；最终缓存哈希
  未变化。健康检查不消耗任何模型 API 调用。
