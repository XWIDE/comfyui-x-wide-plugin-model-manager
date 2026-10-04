# v1.1.0 — 首个发布版本 / First release

> 这份文件是 GitHub Release 的现成文案：在
> <https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/releases/new>
> 里选好标签 `v1.1.0`，把下面横线以内的内容整段粘进正文即可。

---

## 中文

**X-WIDE Plugin & Model Manager** —— 一个纯本地、**只读优先**的 ComfyUI 自定义节点（插件）管理器：
把「启动为什么慢、哪些插件在拖、谁在引用谁、哪些模型其实没人用」摆到台面上。

侧边栏一个页签 → 打开一个**全屏大页面**（也可以**独立浏览器窗口**打开，方便拖到第二个显示器），共 5 页：

| 页 | 它回答的问题 |
| --- | --- |
| ① 启动体检 | 总时长是多少、花在引导 / 启动前脚本 / 节点导入 / 收尾各多少；哪个包的 `prestartup`、`import` 最贵；有没有导入失败的包 |
| ② 插件分析 | 每个包：耗多少秒、注册多少节点、被几个工作流用到、谁在引用它（依赖反查，四层证据都带 `文件:行号`）、风险三色 |
| ③ 工作流分析 | 工作流最后改动 / 最后读取时间、年龄分桶、用了哪些插件、有没有引用已禁用插件的节点 |
| ④ 模型分析 | 模型目录的体积与数量、**谁都没提**的（候选，不删除）、按引用强度分档（源码点名 / 约定目录 / 没人提） |
| ⑤ 动作记录 | 每次禁用 / 恢复的时间、对象、`改名前 → 改名后`、成功失败，可一键恢复 |

### 唯一会改动文件系统的动作是「禁用 / 恢复」

把 `custom_nodes/<包名>` 改名成 `<包名>.disabled`（ComfyUI 自己的约定，`nodes.py` 会跳过 `.disabled`），
**不删任何文件**，改回名字即恢复；需要重启 ComfyUI 生效。**模型页没有任何删除或批量操作。**

- 禁用前一定会先把风险摆出来（谁在引用它、哪些工作流在用、禁用后会缺哪些节点）；
  **有牵连时必须手打确认词**；
- 批量禁用同样要手打确认词，**单次最多 60 个**；
- 可选的「自动处理」（**默认不勾选**）：勾上时先弹一次确认，之后**每次进入「插件分析」页都会自动跑一遍** ——
  扫描并禁用「从未被任何工作流使用」或「超过 N 天（默认 90 天）没被用过」的包。
  服务端硬保护：**一次最多 12 个**、且不超过已启用包总数的一半；源码 3 天内改过的、被别的包真正 `import` 的、
  内置保护名单里的一律不动。跑完弹结果窗并留**一键恢复**，每一步都写进第 5 页。
  另有「**先看计划（不改动任何东西）**」按钮，先看清楚再决定。
- 不勾选时**只扫描**，不启动任何后台轮询、不注册启动脚本，**不会拖慢 ComfyUI 启动**。

### 界面

- 侧边栏分四组：**品牌**（X-WIDE 品牌图 + 标题 + 副标题 + **版本号** / **GPL-3.0 开源协议**徽标 + 一句**免责声明**）/ **作者与链接** / **自动处理** / **常用操作**；
- 完整面板页眉三段式（品牌图 + 标题 + 版本徽标 + 协议链接 / 作者信息排 / 按钮组），窄窗口自动换行；
- 「**打开完整面板**」在新标签页里打开 —— 它就是一个普通网页
  `http://<地址>:<端口>/xwide/plugin-manager/ui`，页签可深链（`#packs`、`#workflows`…），
  也能拖到第二个显示器上常驻；老前端（没有侧边栏 API）下退化成右下角浮动按钮；
- 模型页可按**类型分组**（`unet` / `text_encoders` / `diffusion_models`…），一组一个可折叠块，
  标题写「N 个 · 合计体积」；搜索框是防抖的，几百行也不卡；
- 模型页色条下面那排**色块本身就是过滤器**：点一下只看这一档、再点一下取消，和「只看某一档」的按钮共用同一个状态；
- 点「**重新分析**」立刻显示 `◐ 正在重新分析… 已经等了 N 秒` 并锁住按钮，跑完提示用时 —— 不再「点了没反应」；
- 执行「自动处理」时三个按钮会一起锁住、窗口里显示进行到第几秒，**连点也只跑一次**。

### 安装

- **ComfyUI Manager**：「Install via Git URL」填
  `https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager`，或者等 Registry 收录后直接搜
  `X-WIDE Plugin & Model Manager`；
- 手动：`git clone` 到 `ComfyUI/custom_nodes/` 后重启 ComfyUI；
- 装好后 **Ctrl + F5 硬刷新**页面，左侧边栏会出现「插件分析」页签；
  也可以直接开 `http://127.0.0.1:8188/xwide/plugin-manager/ui`（端口按你自己的改）。

### 兼容性

- Windows / macOS / Linux；ComfyUI 0.3 及以上（实测 0.38.2）；Python 3.10+；
- **不写死路径与端口**：先问 ComfyUI 自己（`folder_paths` / 实际监听地址），拿不到再按插件位置推断，
  最后才用平台常规位置兜底，随时可用 `XWIDE_*` 环境变量覆盖；
- **不依赖任何第三方库**：只用 ComfyUI 自带的 `aiohttp` 与 Python 标准库（`psutil` 有就用，没有也能跑）；
- 前端没有侧边栏 API 时退化成页面右下角浮动按钮，**独立窗口方式始终可用**；
- 插件目录只读也能用（数据文件自动写到 `user` 目录下）。

### 验证

- 后端：8 个 Python 文件 `py_compile` 通过；对真实运行中的 ComfyUI 跑 HTTP/路由集成探针 **11/11**（含
  「`/open` 拒绝越界路径」这类负例）；
- 前端：`node --check` 通过；假 DOM 冒烟**三种模式全过**（页面内 / 独立窗口 / 打开「自动处理」）；
- 端到端：自动化「换台机器」测试 **30/30** —— 把插件整包复制到临时目录、用 Comfy Registry 风格的目录名、
  在**没有 ComfyUI 的 Python 进程**里跑：路径推导、快照兜底、四个页签的数据、自动处理的判断、
  **真实的禁用 → 恢复往返**、越界路径与「不许动自己」的护栏。
- 说明：依赖边来自源码 / 文档的名字匹配，**静态分析不等于运行时验证**；证据列里的 `文件:行号`
  是给使用者自己判断用的。

---

## English

**X-WIDE Plugin & Model Manager** — a purely local, **read-only-first** manager for ComfyUI custom
nodes (plugins): it puts "why startup is slow, which plugins drag it down, who depends on whom, and
which models nobody references" on the table.

One sidebar tab opens a **full-page UI** (also available in a **standalone browser window**, handy on a
second monitor), with five pages: startup timings (total plus boot / prestartup / node import / tail,
with per-pack cost tables), plugin analysis (cost, registered node count, workflow usage, reverse
dependency lookup with `file:line` evidence, three-colour risk marks), workflow analysis (age buckets,
plugins used, missing nodes), model analysis (size/count, unreferenced candidates, three tiers — never
deletes anything), and an action log with one-click restore.

### The only filesystem write is disabling a plugin

`custom_nodes/<pack>` is renamed to `<pack>.disabled` (ComfyUI's own convention — `nodes.py` skips
`.disabled`). **Nothing is ever deleted**; renaming it back restores it. A ComfyUI restart is required
for either direction.

- Risks are always listed before disabling (who imports it, which workflows use it, which nodes would go
  missing); **anything entangled requires you to type a confirmation word**;
- **Bulk disable** requires the confirmation word too and is capped at **60 packs per run**;
- Optional **autopilot** (**off by default**): ticking it asks once, then **runs every time you open the
  Plugins page** — it disables packs that are used by no workflow, or untouched for N days (default 90).
  Server-side hard guards: **at most 12 per run**, never more than half of the enabled packs, never packs
  whose source changed within 3 days, never packs that another pack really imports, never the built-in
  protected list. It shows a result dialog with **one-click restore** and logs every step to page 5.
  There is also a **"show the plan first (changes nothing)"** button.
- With autopilot off, the plugin **only scans** — it registers no startup script and no background timer,
  so it **does not slow ComfyUI down**.

### Interface

- The sidebar has four groups: **brand** (X-WIDE logo + title + subtitle + **version** badge +
  **GPL-3.0** badge + a one-line **disclaimer**) / **author & links** / **autopilot** / **common actions**;
- The full panel header has three parts (logo + title + version badge + licence link / author row /
  button group) and wraps on narrow windows;
- "**Open full panel**" opens in a new browser tab — it is an ordinary web page at
  `http://<host>:<port>/xwide/plugin-manager/ui`, tabs are deep-linkable (`#packs`, `#workflows`, …),
  so it can live on a second monitor; on an older front end without the sidebar API it degrades to a
  floating button in the corner;
- The Models tab can **group by type** (`unet` / `text_encoders` / `diffusion_models` …), one collapsible
  block per type with "N files · total size" in the header; the search box is debounced, so hundreds of
  rows stay responsive;
- **The colour chips under the bar filter as well**: click one to see just that tier, click again to
  clear; it shares its state with the "only one tier" buttons below, so both stay in sync;
- Clicking "**Re-analyse**" immediately shows `◐ re-analysing… N s elapsed` and locks the button, then
  reports the elapsed time — no more "I clicked and nothing happened";
- While autopilot runs, all three buttons are locked and the window shows the elapsed time — **clicking
  repeatedly still runs it once**.

### Install

- **ComfyUI Manager** → "Install via Git URL" with
  `https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager`, or search for
  `X-WIDE Plugin & Model Manager` once the Registry entry is live;
- or `git clone` into `ComfyUI/custom_nodes/` and restart ComfyUI;
- then **Ctrl + F5** to hard-refresh; the "插件分析 / Plugins" sidebar tab appears. You can also open
  `http://127.0.0.1:8188/xwide/plugin-manager/ui` directly (adjust the port).

### Compatibility

- Windows / macOS / Linux; ComfyUI 0.3+ (measured on 0.38.2); Python 3.10+;
- **No hard-coded paths or ports**: it asks ComfyUI first (`folder_paths`, the real listen address),
  falls back to inferring from the plugin's own location, then to per-platform defaults, and everything
  can be overridden with `XWIDE_*` environment variables;
- **No third-party dependencies**: only the `aiohttp` that ships with ComfyUI plus the standard library
  (`psutil` is used when present, never required);
- If the front end has no sidebar API it degrades to a floating button in the corner, and the standalone
  window always works;
- A read-only plugin folder is fine (data files move under `user/`).

### Verification

- Backend: `py_compile` on all eight Python files; an HTTP/route integration probe against a real running
  ComfyUI: **11/11** (including negative cases such as `/open` refusing out-of-bounds paths);
- Front end: `node --check`; a fake-DOM smoke run in **three modes** (in-page / standalone / autopilot
  enabled) — all pass;
- End to end: an automated "different machine" test, **30/30** — the whole plugin copied into a temp
  folder under a Comfy Registry–style folder name, exercised **in a Python process with no ComfyUI
  installed**: path resolution, snapshot fallback, data for four pages, autopilot decisions, a **real
  disable → restore round trip**, and the out-of-bounds / "never touch yourself" guards.
- Note: dependency edges come from name matching in source and docs, so **static analysis is not runtime
  verification** — the `file:line` evidence is there for you to judge.
