# HyperChE 生产域名迁移

日期：2026-10-08。按项目所有者要求，生产域名由
`hyperche.fallrain0905.top` 更改为 `cupzhouth.top`。

- 主站：`https://cupzhouth.top`
- 汇报：`https://cupzhouth.top/report/hyperche-demo.html`
- DNS：公共 Google DNS 与服务器解析均返回 `154.219.99.75`，未发现 AAAA 记录。
- 部署模板、证书路径、默认 CORS 来源和 README 同步到新域名。
- 已有管理员登录邮箱及密码保留；新安装示例邮箱为 `admin@cupzhouth.top`。
- 应用加密密钥、PostgreSQL、Redis、业务卷和最终缓存沿用现有安装。

## 完成验收（2026-10-09，Asia/Taipei）

已部署提交：`43401a149c1e8388745c577f7552433d5e8ab09b`。
此后的文档提交不改变该应用镜像版本。

| 验证项 | 结果 |
| --- | --- |
| HTTPS | 公共域名证书校验通过，SAN 包含 `cupzhouth.top`，有效期至 2027-01-06 14:57:17 UTC |
| HTTP | 首页返回 301，转向 `https://cupzhouth.top/` |
| 首页 | HTTPS 返回 200；浏览器实际显示首页与登录入口 |
| 汇报与 Word | HTTPS 均返回 200；Word 内容验证为有效 ZIP 容器 |
| 公开缓存图谱 | API 返回 25 个实体、12 条超边 |
| CORS | 新 HTTPS 来源获准，旧域名来源被拒绝 |
| 登录与权限 | 现有管理员登录通过，用户 ID 与迁移前一致；Cookie 保持 Secure/HttpOnly，未登录管理员访问返回 401 |
| 最终缓存 | 全部 10 个文件 SHA-256 未变，最终库仍为只读 F1，清空请求返回 403 |
| 持久化 | 沿用原数据卷、管理员账号、私有配置和应用密钥 |
| 旧站点 | 已备份并停用旧 HyperChE enabled-site 链接；旧配置保留供回滚 |
| 原中转服务 | 原 API Nginx 配置与迁移前备份哈希相同，`newapi` 与数据库容器仍健康 |
| 证书续期 | Certbot timer 已启用并运行；证书配置保留 ACME webroot 与 Nginx reload hook，未进行续期 dry-run |

升级前备份位于 `/opt/hyperche/backups/0867e28-before-domain-migration`，
包括 PostgreSQL、私有环境、业务卷与宿主 Nginx 站点配置。没有删除数据卷。
管理员私下交付文件已更新为新 URL，登录邮箱及密码保留。

模型渠道尚未配置，`cache_ready=true`、`models_ready=false`、`ready=false`。
公开 JSON/SSE 查询返回明确的 503 配置提示；管理员录入渠道后再验收真实问答。
本次域名迁移未调用 embedding 或生成 API。
