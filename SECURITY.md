# 安全策略

## 支持范围

只维护 `main` 分支和最新 release。旧版本的问题请先升级再复现。

## 报告问题

- 一般 bug：开 [Issue](https://github.com/lclGithub/ha-siseli-solar/issues)。
- 安全问题（例如凭据泄露、越权、注入）：请不要开公开 Issue，直接用 GitHub 的
  **Report a vulnerability**（仓库 Security 页面）私信维护者。

## 这个集成会接触哪些数据

- 雷零 App 的账号和密码：保存在 HA 配置条目的 `.storage` 里（HA 的云集成普遍如此，
  明文存储）。介意的话请单独注册一个账号。
- access / refresh token：同样保存在配置条目里，用于自动续期。
- 设备数据：只从云端读取，不上传到任何第三方；集成本身没有遥测。

## 使用者的责任

- 不要把自己的 `.storage`、日志、token 贴到 Issue 里；贴日志前先删掉账号、设备 ID、
  序列号和 token。
- 不要把 HA 长期访问令牌或雷零账号密码交给 AI agent；用
  [AI 安装指引](docs/AI-INSTALL.md) 里的提示词，它只需要文件权限。
- 本项目以 MIT 许可发布，按「现状」提供，不承诺可用性和安全性。
