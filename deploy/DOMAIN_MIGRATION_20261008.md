# HyperChE 生产域名迁移

日期：2026-10-08。按项目所有者要求，生产域名由
`hyperche.fallrain0905.top` 更改为 `cupzhouth.top`。

- 主站：`https://cupzhouth.top`
- 汇报：`https://cupzhouth.top/report/hyperche-demo.html`
- DNS：公共 Google DNS 与服务器解析均返回 `154.219.99.75`，未发现 AAAA 记录。
- 部署模板、证书路径、默认 CORS 来源和 README 同步到新域名。
- 已有管理员登录邮箱及密码保留；新安装示例邮箱为 `admin@cupzhouth.top`。
- 应用加密密钥、PostgreSQL、Redis、业务卷和最终缓存沿用现有安装。

服务器切换、TLS 签发及公开链接验收结果将在执行后补充。
