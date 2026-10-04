# X-WIDE Plugin & Model Manager

<img src="https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/logo-wordmark.png" alt="X-WIDE — I BELIEVE" width="360">

[English](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/README.en.md) | **中文**

![version](https://img.shields.io/badge/version-1.1.0-blue)
![license](https://img.shields.io/badge/license-GPL--3.0-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

一个**纯本地、只读优先**的 ComfyUI 自定义节点（插件）管理器：把「启动为什么慢、哪些插件在拖、谁在引用谁、哪些模型其实没人用」摆到台面上。

当前版本：**1.1.0**（首个发布版本，五页签 + 可选的「自动处理」）—— 变更明细见 [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md)，本版本的 Release 文案见 [docs/RELEASE_NOTES_v1.1.0.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/RELEASE_NOTES_v1.1.0.md)。

**唯一会改动文件系统的动作是「禁用 / 恢复」**，而且只是给插件目录**改名**：

```
ComfyUI/custom_nodes/<包名>   ⇄   ComfyUI/custom_nodes/<包名>.disabled
```

`.disabled` 是 ComfyUI 自己认的约定（`nodes.py` 会跳过它）。**不删任何文件**，把名字改回来就恢复；禁用 / 恢复都要**重启 ComfyUI** 才生效。

> **它不会删模型、不动 pip 包、不联网、不改 ComfyUI 自身的任何文件。** 模型页只有「打开文件夹」，没有任何删除按钮。

当前版本：**1.1.0**（首个发布版本）—— 变更明细见 [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md)。

> **关于发布：上架 Comfy Registry 是手动步骤。** 本仓库的 GitHub Actions 只支持手动触发
> （配好 `REGISTRY_ACCESS_TOKEN` 后，到 Actions 页面点 **Run workflow**），
> **push 代码本身不会自动发版** —— 这是刻意的：插件的「禁用 / 恢复」会改动文件系统，
> 要先在本地把插件测通再上架。详细步骤见 [docs/发布指南.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/发布指南.md)。

---

## 目录

- [它长什么样](#它长什么样)
- [五个页签](#五个页签)
- [安全边界（请先读这一段）](#安全边界请先读这一段)
- [安装](#安装)
- [使用](#使用)
- [兼容性](#兼容性)
- [目录结构](#目录结构)
- [常见问题](#常见问题)
- [关于作者](#关于作者)
- [许可](#许可)
- [发布方式（给维护者）](#发布方式给维护者)

---

## 它长什么样

入口：ComfyUI 左侧边栏 → **X-WIDE** 页签（方块图标）。侧边栏分成四组，从上到下：**品牌区**（X-WIDE 品牌图 + 标题 + 一句副标题「谁在拖慢启动 · 谁被谁依赖 · 动了谁会坏 · 哪些模型没人用」+ **版本号**与 **GPL-3.0 开源协议**徽标 + 一句**免责声明**）、**作者与链接**（GitHub / B 站）、**自动处理**（开关、处理范围、以及「先看计划 / 按计划执行禁用… / 恢复自动处理禁用的」三个按钮）、**常用操作**（打开完整面板 / 生成报告文件 / 使用说明 / 中文 ⇄ English）；点 **「打开完整面板」** 会在**浏览器新标签页**里打开五页签界面（不再占用画布）。

![侧边栏](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/sidebar.png)

![五页签总览](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/overview.png)

> 下面每个页签都配了截图，全部是在**真机 + 真浏览器**里拍的（完整面板就是一个网页，单独开一个标签页也是同一个它），
> 图片放在仓库的 `docs/images/` 下。想看「禁用前会拦你一道」长什么样，直接翻到 ② 的第二张图。

**它就是一个普通网页**：`http://<你的地址>:<端口>/xwide/plugin-manager/ui` —— 侧边栏那个「打开完整面板」按钮打开的就是它，在新标签页里，可以拖到第二个显示器上常驻、也可以和 ComfyUI 主界面并排看；这个方式不依赖 ComfyUI 前端有没有侧边栏 API。页签支持深链，例如 `…/ui#packs`、`#workflows`、`#models`、`#log`。脚本是**从插件自己的路由**（`/xwide/plugin-manager/web/xwide_plugin_manager.js`）加载的，所以插件目录被改名、或者由 Registry 安装到别的目录名下，也照样能打开（后面还会依次回退到 ComfyUI 的 `/extensions/<目录名>/`）。

页眉分三段：左边是**标题组**（品牌图 + 插件名 + 版本徽标 + GPL-3.0 协议链接），中间是**作者信息排**（作者 X-WIDE、版本号点开就是 GitHub 仓库、GitHub 仓库、更新日志、B 站主页、问题反馈），右边是**按钮组**（重新分析 / 生成报告文件 / 看报告 / 使用说明 / 中文 ⇄ English / 关闭，窄窗口会自动换行）。点**「重新分析」**时页眉下面会立刻显示 `◐ 正在重新分析… 已经等了 N 秒`、按钮锁住，跑完提示「重新分析完成，用时 X 秒」（不再出现「点了没反应」）。

---

## 五个页签

### ① 启动体检

从启动日志读出「**进程启动 → 界面就绪**」的总时长，并拆成四段：

| 分段 | 含义 |
| --- | --- |
| 引导 | 解释器 / 依赖导入等启动前的基础工作 |
| 启动前脚本 | `prestartup_script.py` 之类的前置脚本 |
| 节点导入 | 逐个 `custom_nodes` 包的导入耗时 |
| 收尾 | 导入结束到服务就绪的收尾工作 |

另外给出：

- **两张按包排序的耗时表**：`prestartup` 与 `import` 各一张，谁最贵一眼可见；
- **导入失败的包**（日志里的 `IMPORT FAILED` 之类）；
- **降级提示**（某个包只导入了一部分、或某些能力没装上）。

![启动体检](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/startup.png)

### ② 插件分析

扫 `custom_nodes` 下每个包的源码 / 文档里的依赖关系。**四层证据**，每一层都给出 `文件:行号` 的原文，方便自己核对：

| 层 | 证据 |
| --- | --- |
| 1 | 源码里的 `import` 语句 |
| 2 | 动态加载（`importlib` 之类按名字取模块） |
| 3 | 列表声明（requirements / 依赖清单里写了包名） |
| 4 | 文档提及（README、注释里提到） |

再扫你的工作流用到了哪些节点类型，于是每个包都有：

- **启动耗时**、**注册节点数**；
- **简介**：这个包是干什么的（读它的 `pyproject.toml` 的 `description`，没有就读 README 首段；读不到就留空，不编造）；
- **被几个工作流用到**、**谁在引用它**（依赖反查：哪些启用中的包引用了它）；
- **风险三色**：🟢 绿色可以清理 / 🟡 黄色有风险 / 🔴 红色尽量别动（基础设施包、或一大堆包都依赖它）；
- **依赖索引扫描状态**：本轮复用了多少包、重扫了多少包、花了多少秒、缓存写盘有没有失败。

> 依赖索引是**按包增量**的：源码没变过的包直接复用缓存，只有改动过的包会重扫。

![插件分析](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/plugins.png)

禁用**有牵连**的包时（被别的插件引用、或工作流在用），先弹这张清单：把证据列出来，确认词必须**手打**
（`disable <包名>`），打错只会提示、不会执行。这一层拦的就是「手快点错、然后少一堆节点」。

![禁用前的风险确认](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/risk-confirm.png)

### ③ 工作流分析

逐个工作流列出：

- **最后改动时间 / 最后读取时间**，以及**年龄分桶**（7 天以内 / 8–30 天 / 31–90 天 / 90 天以上）——**分桶可以点**：点一下只看这一类、再点一下取消，选中时会高亮，旁边还有一个「只显示高亮的内容」；
- **用了哪些插件**（默认显示前 4 个 + `+N`，鼠标悬停能看到那个包的简介）；
- **是否引用了「已禁用」插件的节点**，以及**是否有当前没注册的节点**（缺节点）。判定缺节点时会**先在前端 JS 里找一遍**，避免把「只在 JS 里注册的节点」误报成缺失；
- **插件反查工作流**：每个插件被哪些工作流用到。

> 「最后读取时间」来自文件系统的访问时间。**它不能当成「用过」的证据** —— 很多文件系统默认不更新它，而且会被杀毒 / 备份 / 网盘 / 资源管理器预览刷新。只当参考。

![工作流分析](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/workflows.png)

### ④ 模型分析

**只读**清点模型目录：体积与数量、哪些没被任何工作流引用，并把「没被引用」的按**引用强度**分三档（源码点名 / 约定目录 / 谁都没提），每档都给证据。

表格有**两种看法**，用「只看某一档」里的 **按类型分组** 勾选框切换（默认开）：

- **按类型分组**：同一个 `类型`（`unet` / `text_encoders` / `diffusion_models` / `loras` …）的模型收进一个可折叠块，块标题写着「N 个 · 合计体积」，块之间按体积从大到小排 —— 找某一类不用在长表里翻；
- **平铺长表**：取消勾选就回到带「类型」列的平铺表。

搜索框是**防抖**的：敲键时不会每按一下都重画整张表（几百行也能跟得上手速）。

**色条下面那排色块本身就是过滤器**：点一下「谁都没提」就只看这一档（再点一下取消），
选中时色块描边高亮；它和下面「只看某一档」的按钮是**同一个状态**，两处高亮永远同步。

下面那张「**约定自动加载目录**」（有什么加载什么）**默认是折叠的**，点开才展开 —— 内容多，但不是每天都要看。

> **这一页不会删除任何文件、也没有任何批量操作**，唯一的动作是「**打开文件夹**」。

![模型分析](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/models.png)

### ⑤ 动作记录

每一次**禁用 / 恢复**都写进 `actions.log`：时间、对象、`改名前 → 改名后`、成功还是失败。页面上可以查看这份记录，并**一键恢复**（不用自己去资源管理器里改目录名）。

![动作记录](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/actions.png)

---

## 安全边界（请先读这一段）

1. **唯一的写操作是改名。** 禁用 = 把 `custom_nodes/<包名>` 改名成 `custom_nodes/<包名>.disabled`；恢复 = 改回来。这是 ComfyUI 自己认的约定（`nodes.py` 会跳过 `.disabled`），**不删任何文件**，改名不丢任何数据。
2. **禁用 / 恢复都需要重启 ComfyUI 才生效。**
3. **不删模型**：模型页没有任何删除按钮，只有「打开文件夹」。
4. **不动 pip 包**：不会 `pip install` / `pip uninstall` 任何东西，也不会删你环境里的库。
5. **不联网**：所有分析都在本机完成，插件自身不发起任何网络请求。
6. **不改 ComfyUI 自身的任何文件**：只读日志、工作流、模型目录清单；写文件只写本插件目录下的缓存与日志。
7. **禁用前必须先把风险摆出来**：界面上会列出「谁在引用它、哪些工作流用到它、禁用后可能会缺哪些节点」；**有牵连时必须手打确认词**才能继续（确认词区分大小写，输入框上方会写明要打什么）。**批量禁用**同样要手打确认词，**单次最多 60 个**。
8. **静态分析 ≠ 运行时验证**：依赖关系来自源码 / 文档的名字匹配。有的包用 `try/except` 静默降级，只能靠「禁用 → 重启 → 看日志」确认。证据列里的 `文件:行号` 就是给你自己判断用的。
9. **可选的「自动处理」**（默认**不勾选**）：勾上时会**先弹一次确认**（写明规则与硬保护），之后**每次进入「插件分析」页都会自动跑一遍**——扫描工作流与依赖，然后禁用「从未被任何工作流使用」或「超过 N 天（默认 90 天）没被用过」的包。服务端硬保护：**一次最多 12 个**（且不超过已启用包总数的一半）；源码 3 天内改过的、被别的插件真正 `import` 的、`KEEP_NEVER` 名单里的包一律不动。跑完弹结果窗（禁用了哪些、预计省多少、失败项）并留一键恢复入口，每一步都记在第 5 页「动作记录」。**不勾选时只扫描，由使用者自己决定**；卡片上的「先看计划」随时可以只看不改，或直接「恢复自动处理禁用的」。

> 执行期间**三个按钮会一起锁住**（灰掉），窗口里显示 `◐ 正在执行禁用… 已经等了 N 秒`；「先看计划」和「按计划执行禁用…」**连点也只跑一次**，计划和结果都显示在**同一个窗口**里（不会看起来像跑了两趟）。
10. **绘世启动器 / 其它启动器的「扩展」列表不认识 `.disabled` 后缀**：已禁用的包在那些界面里仍显示为已安装。所以**禁用 / 恢复请在本面板里做**。

### 出事了怎么退回去

- 面板里：**第 5 页「动作记录」→ 点「恢复」**；
- 手动：把 `ComfyUI/custom_nodes/<包名>.disabled` 改名回 `ComfyUI/custom_nodes/<包名>`；
- 干脆不用了：删掉本插件整个文件夹即可，**不留残余**（禁用过的包按上一条改回名字就好）。

---

## 安装

**方式一：ComfyUI Manager（推荐）**

1. 打开 Manager → 搜索 **`X-WIDE Plugin & Model Manager`**（或 `x-wide`、`plugin manager`）；
2. 安装后重启 ComfyUI，刷新页面（`Ctrl` + `F5`）。

**方式二：手动**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager
```

重启 ComfyUI 后再硬刷新一次页面（`Ctrl` + `F5`）。

本插件**不需要**额外依赖：只用 ComfyUI 自带的 `aiohttp` 与 Python 标准库。

> 插件内部**不依赖自己的目录名**：文件夹叫 `X-WIDE_plugin_model_manager` 还是 `comfyui-x-wide-plugin-model-manager` 都能跑。

---

## 使用

1. 重启 ComfyUI，硬刷新页面；
2. 左侧边栏 → **X-WIDE** 页签 → **「打开完整面板」**（它在新标签页里打开；也可以直接访问 `http://<地址>:<端口>/xwide/plugin-manager/ui`）；
3. 按页签看：先看 **① 启动体检** 找「谁在拖慢启动」，再去 **② 插件分析** 看风险三色，最后才考虑禁用；
4. 禁用任何一个包之前，**先把它展开**看证据（工作流用到？别的包引用？）；
5. 禁用 → **重启 ComfyUI** → 回到 **① 启动体检** 对比启动时长、到 **③ 工作流分析** 看有没有缺节点；
6. 有问题就 **⑤ 动作记录 → 恢复**，再重启。

---

## 兼容性

- **系统**：Windows / macOS / Linux 都可以用；
- **ComfyUI**：0.3 及以上（开发与实测环境：ComfyUI **0.38.2** + 前端 1.53.6）；**Python 3.10+**；
- **依赖**：**只用 Python 标准库 + ComfyUI 自带的 `aiohttp`**，不装任何第三方包；`psutil` 是可选加速项（有就用，没有就改用各平台的系统调用）；
- **前端**：侧边栏入口需要较新的 ComfyUI 前端（有 `registerSidebarTab`）。**没有这个 API 的老前端上侧边栏入口不出现**（控制台会打印一条提示），但**网页方式始终可用**、和前端版本无关：直接打开 `http://<地址>:<端口>/xwide/plugin-manager/ui`，HTTP 路由也照样能用；
- **路径不写死**：优先**问 ComfyUI 自己**（`folder_paths`）来推导 `custom_nodes` / `models` / `user` / 工作流 / 日志的位置，拿不到才按插件自身位置往上推，再拿不到才用平台常规位置兜底；随时可以用环境变量覆盖；
- **环境变量覆盖**（`.disabled` 之外的路径来源）：

  | 变量 | 覆盖什么 |
  | --- | --- |
  | `XWIDE_COMFY_ROOT` | ComfyUI 根目录（其它路径从这里推） |
  | `XWIDE_NODES_DIR` | `custom_nodes` 目录 |
  | `XWIDE_MODELS_DIR` | `models` 目录 |
  | `XWIDE_WORKFLOWS_DIR` | 工作流目录 |
  | `XWIDE_LOG_FILE` | 要解析的 ComfyUI 日志文件 |
  | `XWIDE_USER_DIR` | ComfyUI 的 `user` 目录 |
  | `XWIDE_DATA_DIR` | 本插件自己的数据目录（缓存 / 日志） |
  | `XWIDE_SERVER` | 要连的 ComfyUI 服务地址 |
  | `XWIDE_MODEL_LOGS` | 设为 `0` 关闭可选的模型加载记录钩子 |

  > 用不到这些变量时**什么都不用设置**，插件自己会去找。本页不重复代码，最终以代码里的实现为准。
  >
  > **插件目录只读时也能用**：数据文件（缓存 / `actions.log` / 模型加载记录）默认写在插件自己目录里；目录不可写时自动退到 `user` 目录下的 `X-WIDE_plugin_model_manager/`，所以 `custom_nodes` 是只读挂载的打包安装也能跑。

### 兼容性验证到什么程度（写清楚，不吹）

| 验证方式 | 覆盖到什么 |
| --- | --- |
| **真机实测**（Windows + ComfyUI 0.38.2 + Python 3.13） | 五个页签、禁用 → 重启 → 恢复整条流程、自动处理（勾选后执行 / 一键恢复）、完整面板（新标签页 / 独立窗口）、全部 HTTP 路由 |
| **自动化「换台机器」测试** | 把插件整包复制到临时目录、目录名改成 `x-wide-plugin-model-manager`（Comfy Registry 装出来的命名），在一个**完全没有 ComfyUI 的 Python 进程**里跑：路径推导、快照兜底、四个页签的数据、自动处理的判断、真实禁用 / 恢复、越界路径与「不许动自己」的护栏 —— 30 项全过 |
| **自动化分支测试**（把平台常量与 `subprocess` 换成假的，真跑各平台分支） | Linux：`xdg-open` → `gio open` → `nautilus` 逐级退让、定位文件时打开所在目录、三个都没有时给出明确错误、`/proc` 取进程启动时间（`btime` + `starttime / SC_CLK_TCK`）、没有 `btime` 时返回空而不是抛错；macOS：`open` / `open -R`、没有 `psutil` 时降级返回空；Windows：`os.startfile` 开目录、`explorer /select,` 定位文件；再加 `filetime_to_unix` 换算、`server_url()` 的兜底与 `XWIDE_SERVER` 覆盖、以及「导入插件时不干活」的检查（没有 `prestartup_script.py`、库模块顶层没有循环 / 裸调用 / `atexit` / `Timer` / `time.sleep`）—— 29 项全过 |
| **仅代码审查（没有真机跑过）** | 上面这些分支在真 macOS / Linux 上的实际表现（命令是否存在、桌面环境差异、权限限制） |

> 一句话：**Windows 是实测过的**；macOS / Linux 的每条平台分支都写了、也都有兜底（拿不到就退化显示或走日志，绝不报错中断），并且有自动化分支测试跑过，但**没有真机跑过**。在 macOS / Linux 上遇到问题欢迎开 issue。
>
> 反向的一条：**插件在 ComfyUI 进程之外被导入时**（脚本、别的工具），本进程的节点注册表是空的，这时一律以磁盘快照为准 —— 不会因为“看起来没人用”就给出错误的禁用建议。

### 可选的模型加载记录钩子

- 只**记录**、**不拦截**模型加载；
- 关掉：`XWIDE_MODEL_LOGS=0`（或 `off` / `false` / `no` / `none`）；
- 钩子自己出错也**不会影响加载本身**（异常一律吞掉）；
- 记录文件落在本插件的数据目录里。

---

## 目录结构

```
comfyui-x-wide-plugin-model-manager/
├── __init__.py                 # 注册本地 API + 可选的模型加载记录钩子
├── analyzer.py                 # 分析逻辑：源码 / 文档依赖、工作流、启动日志解析
├── collector.py                # 把分析结果整理成给界面用的 JSON + 内存缓存
├── pages.py                    # 启动体检 / 工作流分析 / 模型页桥接 / 加载记录
├── modelscan.py                # 模型目录扫描与分档
├── manager.py                  # 禁用 / 恢复（改名 + 护栏 + actions.log + 批量）
├── autopilot.py                # 「自动处理」：挑候选 + 硬保护 + 执行 + 一键恢复
├── web/xwide_plugin_manager.js # 前端：侧边栏入口 + 完整面板（五页签）
├── web/logo_xwide.png          # 品牌图（侧边栏 / 页眉用的横版 logo）
├── web/logo_xwide_icon.png     # 方形图标（Registry Icon）
├── pyproject.toml              # Comfy Registry 元数据
├── CHANGELOG.md                # 更新日志
├── NOTICE                      # 版权与来源说明
├── LICENSE                     # GPL-3.0
└── docs/                       # 发布指南 + Release 文案 + 图片（docs/images/：README 截图、品牌图 logo-wordmark.png、Registry 横幅 banner.png）
```

运行期还会在本插件目录下生成几个缓存 / 日志文件（`_*.json`、`_model_loads.jsonl`、`actions.log`），
它们**只在本地**，已经写进 `.gitignore`，不会被提交；插件目录不可写时会改写到 `user` 目录下。

---

## 常见问题

**Q：它会删我的插件或模型吗？**
A：不会。唯一的写操作是把 `custom_nodes/<包名>` 改名成 `<包名>.disabled`，以及写自己目录下的缓存 / 日志。模型页没有任何删除功能。

**Q：禁用之后为什么节点还在 / 还在报错？**
A：禁用要**重启 ComfyUI** 才生效。重启后如果工作流里还引用着它的节点，第 3 页「工作流分析」会把「缺节点」列出来。

**Q：我把目录名改回去了，但界面里还显示「已禁用」？**
A：界面数据有缓存。重启 ComfyUI 或在面板上强制刷新一次即可。

**Q：点禁用的时候提示要输入确认词，确认词是什么？**
A：界面会写明。**有牵连的包**（被别的启用中的包引用、或你的工作流正在用）必须手打才能继续，这是故意的 —— 这类包禁用后 ComfyUI 通常**不会**报 `IMPORT FAILED`，而是**静默少几个节点**，很难第一时间发现。**批量禁用同样要手打，单次最多 60 个。**

**Q：第一次打开「插件分析」很慢？**
A：第一次要重建依赖索引，要扫一遍所有包的源码；之后只有源码改动过的包会重扫，剩下的直接复用缓存。耗时的主要瓶颈在文件系统（杀毒 / 网盘 / 索引驱动会明显拖慢读取）。

**Q：「最后读取时间」显示我很久没开过某个工作流，但我明明开过？**
A：这个时间来自文件系统的访问时间，**很多系统默认不更新它**，而且会被杀毒 / 备份 / 网盘 / 资源管理器预览刷新。只当参考。

**Q：模型页说某个模型「谁都没提」，能删吗？**
A：**这一页只负责告诉你「没人提」，不负责让你删。**「谁都没提」只是**候选**：可能是改名后的副本、可能是代码里动态拼出来的路径、也可能只是还没存成工作流的实验。本插件不提供删除，删除请自己确认后再操作。

**Q：能关掉模型加载记录吗？**
A：可以，设环境变量 `XWIDE_MODEL_LOGS=0`。它只记录、不拦截。

**Q：安全吗？会上传我的数据吗？**
A：不会。所有分析都在本机完成，插件自身不联网。

---

## 关于作者

| | |
| --- | --- |
| <img src="https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/logo-wordmark.png" alt="X-WIDE" width="160"> | **X-WIDE** |
| GitHub 主页 | <https://github.com/XWIDE> |
| 作者主页（B 站） | <https://space.bilibili.com/374064919> |
| 本插件仓库 / 下载页 | <https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager> |
| Comfy Registry 发布页 | <https://registry.comfy.org/publishers/xwide> |
| 问题反馈 | <https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/issues> |

---

## 许可

- 本项目以 **GPL-3.0** 授权，完整许可文本见 [LICENSE](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/LICENSE)；
- 版权与来源说明（含「只用到 ComfyUI 自带的 `aiohttp` 与标准库」的声明）见 [NOTICE](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/NOTICE)；
- 变更明细见 [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md)。

---

## 发布方式（给维护者）

**发布是手动步骤**：`.github/workflows/publish_action.yml` 只保留了 `on: workflow_dispatch:`
（没有 `push` 触发器）。配好 `secrets.REGISTRY_ACCESS_TOKEN` 之后，到
<https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/actions/workflows/publish_action.yml>
点 **Run workflow** 才会发布到 Comfy Registry；**push 代码不会自动发版**。

这样做是因为插件的「禁用 / 恢复」会改动文件系统，**建议先在本地测试通过（含禁用 → 重启 →
恢复一整套流程）再发布**。想改回「push 到 `main` 且改了 `pyproject.toml` 就自动发布」，
workflow 文件顶部注释里给了可直接拷回的 `push:` 片段。完整步骤见
[docs/发布指南.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/发布指南.md)。
