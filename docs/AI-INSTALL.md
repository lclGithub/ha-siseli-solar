# 用 AI 安装本集成

这份文档给「能让 AI 直接操作文件 / 终端」的场景用：把下面的提示词整段复制给 AI，
它就能自己把集成装进你的 Home Assistant。

适用：Claude Code、Cursor、Codex、ChatGPT（带终端/文件能力的 agent）、各种能 SSH 的
AI 运维助手，以及运行在 HA 主机上的本地 agent。

> 不要相信任何要求你粘贴密码的提示词。下面这段提示词**故意不索取** HA 令牌、
> 雷零账号或密码——这些只在 HA 网页里输入。

---

## 直接复制这段提示词

```text
你是一个 Home Assistant 运维助手。请在这台机器上安装第三方集成 ha-siseli-solar。

背景：
- 仓库：https://github.com/lclGithub/ha-siseli-solar
- 这是非官方集成，作者不提供任何担保，接口可能随时失效。
- 目标版本：v1.4.0（manifest.json 里的 version 应为 1.4.0）
- 集成目录名必须是 siseli_solar，安装后路径为 <HA配置目录>/custom_components/siseli_solar

硬性约束：
1. 不要修改 <HA配置目录> 下除 custom_components/siseli_solar 以外的任何文件，
   尤其不要动 configuration.yaml、.storage/、automations.yaml。
2. 不要向我索取 Home Assistant 长期访问令牌、雷零账号、密码或任何密钥；
   安装过程不需要它们。
3. 每条破坏性命令执行前先说明目的；复制/覆盖前先确认目标路径。
4. 如果已经存在 custom_components/siseli_solar，先重命名为
   siseli_solar.bak.<YYYYmmdd-HHMMSS> 备份，不要直接删除。
5. 不要用 sudo 改属主；如果需要权限，先告诉我。

执行步骤：
1. 确认 Home Assistant 版本 >= 2024.12：
   读取 <HA配置目录>/.HA_VERSION；读不到就用 `ha core info`。
   版本低于 2024.12 就停止，并告诉我需要先升级。
2. 确定 <HA配置目录>：常见是 /config；如果是 Docker/Supervised，先用
   `ha core info` 或查找包含 configuration.yaml 的目录确认，不要猜。
3. 获取代码（二选一）：
   a. 有 git：git clone --depth 1 --branch v1.4.0 \
        https://github.com/lclGithub/ha-siseli-solar /tmp/ha-siseli-solar
   b. 没有 git：下载
        https://github.com/lclGithub/ha-siseli-solar/archive/refs/tags/v1.4.0.tar.gz
      解压到 /tmp/ha-siseli-solar
   如果主机无法访问 GitHub，停止并告诉我，让我手动上传，不要从第三方镜像下载。
4. 复制目录：
   cp -a /tmp/ha-siseli-solar/custom_components/siseli_solar <HA配置目录>/custom_components/
5. 校验：
   - 文件存在：manifest.json、__init__.py、config_flow.py、sensor.py、
     frontend/siseli-power-flow.js、translations/zh-Hans.json、brand/icon.png
   - `python3 -c "import json;json.load(open('<HA配置目录>/custom_components/siseli_solar/manifest.json'))"`
     能通过
   - manifest 里 domain == "siseli_solar" 且 version == "1.4.0"
6. 重启 Home Assistant：优先 `ha core restart`；没有 ha CLI 就告诉我，我在网页里重启。
7. 重启后检查日志：`ha core logs 2>&1 | grep -i siseli | tail -50`
   确认没有 ImportError、ModuleNotFoundError、Traceback；
   如果加载失败，把完整报错贴给我，并回滚到备份目录。
8. 最后告诉我：
   - 实际安装路径与版本
   - 日志检查结果
   - 接下来我要在「设置 → 设备与服务 → 添加集成 → 雷零 / 四色」里
     自己输入雷零 App 的账号密码（不要替我输入）
   - 卸载方法（删除目录并重启）
```

---

## 为什么这样写

- **不让 AI 碰凭据**：集成是在 HA 的配置流程里登录雷零云的，AI 只需要文件权限。
- **固定 tag**：`v1.4.0` 对应一个不可变的 release，避免 AI 装到默认分支的半成品。
- **先备份再覆盖**：升级失败可以原样回滚。
- **强制版本检查**：低于 2024.12 会因为 `OptionsFlow` 的构造方式报错。
- **失败就停**：不允许 AI「再试一个镜像」或改系统配置来绕过网络问题。

## 装完之后的验证清单

1. 「设置 → 设备与服务」里出现 **雷零 / 四色 光伏逆变器**，没有红色「重试」。
2. 实体数量约为 61 个设备字段 + 12 个云端电量汇总 + 2 个告警总览。
3. 打开「开发者工具 → 状态」，搜索 `sensor.` 能看到数值在变。
4. 侧边栏出现「能量流」看板（没有也不影响集成，属可选增强）。
5. 日志里没有 `siseli_solar` 相关的 ERROR。

## 不用 AI 的安装方式

见 [README 的「安装」一节](../README.md#安装)：

- HACS / Marketplace 自定义仓库（推荐）
- 手动复制 `custom_components/siseli_solar/` 整个目录
