/*
 * X-WIDE 插件分析管理 —— 前端
 * =====================================================================
 * 侧边栏一个页签 → 打开一个独立大页面，共 5 页：
 *   启动体检 / 插件分析 / 工作流分析 / 模型分析 / 动作记录
 *
 * 设计原则（与用户约定）：
 *   - 只读为主：分析、报告、打开文件夹都不会改动任何东西；
 *   - 唯一会改文件系统的动作是「禁用 / 恢复」= 给 custom_nodes 里的目录改名
 *     （ComfyUI 自己的 .disabled 约定），且每次写 actions.log；
 *   - 模型页不提供任何删除或批量操作，只能“打开文件夹”，人工自己处理；
 *   - 插件页支持批量禁用，但必须先把风险摆出来，并手打确认词。
 */

/*
 * 本文件有两种加载方式（见 __init__.py 的 /ui 路由）：
 *   1) 在 ComfyUI 页面里由扩展加载器加载 —— 这时能拿到 ../../scripts/app.js 的 app；
 *   2) 在独立窗口页面（…/xwide/plugin-manager/ui）里加载 —— 那是个空壳页面，
 *      根本没有 ComfyUI 前端。所以这里**不能写静态 import**：静态 import 失败会让
 *      整个模块直接挂掉，界面一片空白。改成动态 import（顶层 await 在 ES module 里合法）。
 */
const STANDALONE = (() => {
  try {
    return !!window.__XWIDE_STANDALONE__;
  } catch (e) {
    return false;
  }
})();

let app = null;
if (!STANDALONE) {
  try {
    ({ app } = await import("../../scripts/app.js"));
  } catch (e) {
    console.warn("[X-WIDE_plugin_model_manager] 没拿到 ComfyUI 前端（app），将按独立模式运行：", e);
  }
}

const PREFIX = "/xwide/plugin-manager";
const VERSION = "1.1.0";

/* 作者与下载入口（README 与「关于作者」用同一组地址；这里让侧边栏也能一键打开） */
const LINKS = {
  author: "https://space.bilibili.com/374064919",
  repo: "https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager",
  store: "https://registry.comfy.org/publishers/xwide",
  issues: "https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/issues",
  changelog: "https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md",
  license: "https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/LICENSE",
};

/* ------------------------------------------------------------------ 新增文案 */
/*
 * 「独立窗口」和「自动处理」是后加的功能，文案单独放这里，
 * 不去动上面那份 DICT（它有中英两套、几百行，改它容易漏）。
 */
const XT = {
  zh: {
    popout: "新标签页打开",
    popoutTip: "在浏览器里新开一个标签页显示完整面板（可以拖到第二台显示器、也可以和主界面并排看）",
    autoTitle: "自动处理（按规则自动禁用插件）",
    autoOff: "已关闭（建议先点“先看计划”，确认没问题再打开）",
    autoOn: "已开启",
    autoMode: "处理范围",
    autoModeA: "只处理「没有任何工作流用过」的",
    autoModeB: "连「很久没用」的也一起处理",
    autoDays: "多少天没用算“很久”",
    autoPlan: "先看计划（不改动任何东西）",
    autoDo: "按计划执行禁用…",
    autoRestore: "恢复自动处理禁用的",
    autoRestoreAsk: "把“自动处理”禁用的包全部恢复启用？",
    autoWarn: "自动处理只会给 custom_nodes 里的目录改名（加 .disabled），不删任何文件，每一次都写进「动作记录」，随时能一键恢复。但它确实会改动你的环境：禁用后要重启 ComfyUI 才生效，用到那些节点的旧工作流会显示缺节点。不确定就先点「先看计划」。",
    autoWillDisable: "计划禁用 %s 个，预计省 %s 秒",
    autoNone: "没有符合条件的包（都还在用，或者省不出多少时间）",
    autoBlocked: "受保护 / 不能动（%s 个）",
    autoSkipped: "跳过（%s 个）",
    autoOver: "超过单次上限、这次不动（%s 个）",
    autoApplied: "已禁用 %s 个，重启 ComfyUI 后生效",
    autoFailed: "有 %s 个没成功",
    autoNothing: "没有需要处理的（计划为空）",
    autoRestored: "已恢复 %s 个",
    autoEnableAsk: "打开自动处理后，每次进入「插件分析」页都会按下面的规则扫描，并自动禁用符合条件的包（服务端硬保护：一次最多 12 个；源码 3 天内动过的、被别的插件真正依赖的、从不动的包都不会动）。每一步都记在「动作记录」页，随时可以一键恢复。确定打开吗？",
    autoEnableTitle: "打开「自动处理」前请确认",
    autoGuard1: "一次最多禁用 12 个，而且不超过已启用包总数的一半",
    autoGuard2: "源码 3 天内改过、被别的插件真正依赖的、固定名单里的，一律不动",
    autoGuard3: "只改目录名、不删文件；每一步都写进「动作记录」，随时一键恢复",
    autoEnableFoot: "禁用后要重启 ComfyUI 才生效；用到那些节点的旧工作流会显示缺节点。",
    autoRunning: "自动处理正在跑：扫描工作流与插件依赖，然后按规则禁用（第一次要一两分钟）…",
    autoBusyWait: "上一次还在跑，等它结束再点（不要重复点）",
    autoPlanning: "正在按规则算计划（扫描工作流与插件依赖）",
    autoDoing: "正在执行禁用（每禁用一个都写进「动作记录」）",
    autoPhase: "已经等了 %s 秒",
    autoLocked: "执行中…",
    autoResultTitle: "自动处理完成",
    autoResDone: "成功 / 失败",
    autoResSave: "预计省下",
    autoAllDone: "自动处理跑完了：这次没有需要禁用的包",
    autoLast: "上次自动处理",
    autoManaged: "自动处理当前管着 %s 个包",
    autoErr: "自动处理失败：%s",
    autoSaved: "设置已保存",
    autoColName: "包",
    autoColCost: "启动耗时",
    autoColNodes: "节点数",
    autoColWhy: "原因",
    confirmWord: "自动处理",
    autoWarnShort: "勾上后：每次进入「插件分析」页会自动扫描并按规则禁用（只改名、不删文件，随时可一键恢复）。",
    btnOpenFull: "打开完整面板（浏览器标签页）",
    popoutBlocked: "浏览器拦住了新标签页，先在当前页面打开完整面板（也可以手动访问 %s）。",
    sideLinks: "作者与链接",
    sideOps: "常用操作",
    linkRepo: "GitHub",
    linkBili: "B 站",
    sideVer: "版本",
    sideLicense: "开源协议",
    licenseName: "GPL-3.0",
    licenseTip: "以 GPL-3.0 授权发布，完整许可文本见仓库里的 LICENSE 文件",
    disclaimer: "免责声明：本插件按原样提供，不对使用后果作任何担保。「禁用」只是把 custom_nodes 里的目录改名（不删任何文件），随时可一键恢复；请自行确认后再操作。",
    reloadStart: "正在重新分析：重新扫一遍插件目录、工作流与依赖（要几秒到几十秒，别重复点）…",
    reloadDone: "重新分析完成，用时 %s 秒",
    reloadFail: "重新分析失败：%s",
    reloadBusy: "上一次重新分析还在跑，等它结束再点",
    mLegendClick: "点上面的色块＝只看这一档（再点一次取消）；下面的按钮是同一件事。",
    aboutBy: "作者",
    aboutRepo: "GitHub 仓库",
    aboutChangelog: "更新日志",
    aboutBili: "B 站主页",
    aboutIssues: "问题反馈",
    saTip: "完整面板（浏览器标签页）：可以拖到另一台显示器、也可以和主界面并排看。数据来自正在运行的 ComfyUI（%s），关掉本页不影响 ComfyUI 本身。",
    saTipNoUrl: "完整面板（浏览器标签页）：可以拖到另一台显示器、也可以和主界面并排看。关掉本页不影响 ComfyUI 本身。",
  },
  en: {
    popout: "Open in new tab",
    popoutTip: "Open the full panel as a normal browser tab (drag it to a second monitor, or keep it beside the main UI)",
    autoTitle: "Autopilot (disable plugins by rule)",
    autoOff: "Off (run \"Preview plan\" first, then turn it on)",
    autoOn: "On",
    autoMode: "Scope",
    autoModeA: "Only packs no workflow ever used",
    autoModeB: "Also packs unused for a long time",
    autoDays: "Days without use",
    autoPlan: "Preview plan (changes nothing)",
    autoDo: "Disable as planned…",
    autoRestore: "Re-enable what autopilot disabled",
    autoRestoreAsk: "Re-enable every pack disabled by autopilot?",
    autoWarn: "Autopilot only renames folders in custom_nodes (adds .disabled). It deletes nothing, logs every step to Actions, and can be reverted with one click. It does change your environment though: a restart is needed, and old workflows using those nodes will show missing nodes. If unsure, click \"Preview plan\" first.",
    autoWillDisable: "Plan: disable %s pack(s), saves about %s s",
    autoNone: "Nothing qualifies (everything is still used, or saves too little)",
    autoBlocked: "Protected / must not touch (%s)",
    autoSkipped: "Skipped (%s)",
    autoOver: "Over the per-run cap, left alone (%s)",
    autoApplied: "Disabled %s pack(s); restart ComfyUI to take effect",
    autoFailed: "%s failed",
    autoNothing: "Nothing to do (empty plan)",
    autoRestored: "Re-enabled %s pack(s)",
    autoEnableAsk: "With autopilot on, every visit to the Plugins tab scans by the rules below and disables the matching packs automatically (server-side hard limits: at most 12 per run; packs whose source changed within 3 days, packs really imported by other packs, and never-touch packs are left alone). Every action is logged on the Actions tab and can be restored with one click. Turn it on?",
    autoEnableTitle: "Confirm before turning autopilot on",
    autoGuard1: "At most 12 packs per run, and never more than half of the enabled packs",
    autoGuard2: "Packs whose source changed within 3 days, packs really imported by others, and never-touch packs are left alone",
    autoGuard3: "Rename only - nothing is deleted; every step is logged and can be undone with one click",
    autoEnableFoot: "Disabling takes effect after a ComfyUI restart; old workflows using those nodes will show missing nodes.",
    autoRunning: "Autopilot is running: scanning workflows and pack dependencies, then disabling by the rules (the first run takes 1-2 minutes)...",
    autoBusyWait: "The previous run is still going - wait for it to finish (no need to click again)",
    autoPlanning: "Working out the plan (scanning workflows and pack dependencies)",
    autoDoing: "Disabling now (every pack is written to the action log)",
    autoPhase: "waiting %s s",
    autoLocked: "Running...",
    autoResultTitle: "Autopilot finished",
    autoResDone: "Done / failed",
    autoResSave: "Estimated saving",
    autoAllDone: "Autopilot finished: nothing needed disabling this time",
    autoLast: "Last autopilot run",
    autoManaged: "Autopilot currently manages %s pack(s)",
    autoErr: "Autopilot failed: %s",
    autoSaved: "Settings saved",
    autoColName: "Pack",
    autoColCost: "Startup cost",
    autoColNodes: "Nodes",
    autoColWhy: "Reason",
    confirmWord: "autopilot",
    autoWarnShort: "When ticked, entering the Plugins tab scans and disables by rule (rename only, nothing is deleted, one-click restore).",
    btnOpenFull: "Open full panel (browser tab)",
    popoutBlocked: "The new tab was blocked, so the full panel opened in this page instead (you can also open %s manually).",
    sideLinks: "Author & links",
    sideOps: "Actions",
    linkRepo: "GitHub",
    linkBili: "Bilibili",
    sideVer: "Version",
    sideLicense: "License",
    licenseName: "GPL-3.0",
    licenseTip: "Released under GPL-3.0; the full license text is the LICENSE file in the repository",
    disclaimer: "Disclaimer: provided as-is, with no warranty of any kind. \"Disable\" only renames a folder inside custom_nodes (nothing is deleted) and can be undone in one click; please verify before you act.",
    reloadStart: "Re-analyzing: rescanning the plugin folders, workflows and dependencies (a few to tens of seconds — please do not click again)…",
    reloadDone: "Re-analysis finished in %s s",
    reloadFail: "Re-analysis failed: %s",
    reloadBusy: "The previous re-analysis is still running — wait for it to finish",
    mLegendClick: "Click a chip above to show only that tier (click again to clear); the buttons below do the same thing.",
    aboutBy: "By",
    aboutRepo: "GitHub repository",
    aboutChangelog: "Changelog",
    aboutBili: "Bilibili",
    aboutIssues: "Report an issue",
    saTip: "Full panel (browser tab): drag it to a second monitor or keep it beside the main UI. Data comes from the running ComfyUI (%s); closing this page does not affect ComfyUI itself.",
    saTipNoUrl: "Full panel (browser tab): drag it to a second monitor or keep it beside the main UI. Closing this page does not affect ComfyUI itself.",
  },
};

function xt(key) {
  /* 和 t() 一样支持 %s 占位：xt("autoManaged", 3) */
  const d = XT[LANG] || XT.zh;
  let s = d[key];
  if (s === undefined) return t.apply(null, arguments);
  for (let i = 1; i < arguments.length; i++) s = s.replace("%s", arguments[i]);
  return s;
}

/* ------------------------------------------------------------------ 文案 */

const DICT = {
  zh: {
    "title": "X-WIDE_plugin_model_manager",
    "sub": "谁在拖慢启动 · 谁被谁依赖 · 动了谁会坏 · 哪些模型没人用",
    "tab.startup": "启动体检",
    "tab.packs": "插件分析",
    "tab.workflows": "工作流分析",
    "tab.models": "模型分析",
    "tab.log": "动作记录",
    "btn.help": "使用说明",
    "btn.report": "生成报告文件",
    "btn.reportView": "看报告",
    "btn.reload": "重新分析",
    "btn.close": "关闭",
    "closedTitle": "这个标签页可以关掉了",
    "closedHint": "浏览器只允许「由脚本打开」的标签页自己关闭，所以刚才那一下可能没关掉。请按 Ctrl+W、或者点标签页上的 × 把它关掉 —— 关掉本页不影响正在运行的 ComfyUI。",
    "closedBack": "回 ComfyUI 主界面",
    "btn.open": "打开大页面",
    "btn.folder": "打开文件夹",
    "btn.evidence": "证据",
    "btn.more": "详情与证据",
    "btn.less": "收起",
    "btn.disable": "禁用…",
    "btn.enable": "恢复",
    "btn.refresh": "刷新",
    "common.loading": "正在分析，请稍候…（第一次全量扫描要一两分钟，之后走缓存很快）",
    "common.error": "出错了",
    "common.empty": "没有数据",
    "common.cancel": "取消",
    "common.confirm": "确定",
    "common.close": "关闭",
    "common.name": "名字",
    "common.search": "搜索名字…",
    "common.seconds": "秒",
    "common.enabled": "启用中",
    "common.disabled": "已禁用",
    "common.notes": "说明",
    "common.generated": "数据时间",
    "common.cached": "来自缓存",
    "common.all": "全部",
    "common.total": "合计",
    "common.count": "数量",
    "common.size": "体积",
    "common.none": "无",
    "common.warn": "注意",
    "common.copy": "复制",
    "common.copied": "已复制到剪贴板",
    "common.back": "返回",
    "common.sortBy": "排序",
    "common.byCost": "按耗时",
    "common.byName": "按名字",
    "common.bySize": "按体积",
    "common.byMtime": "按最后改动",
    "common.pluginDirs": "插件目录",
    "common.loadingPacks": "正在分析插件（第一次要重建依赖索引，约 2–3 分钟；进度写在 ComfyUI 日志的 [deps] 行里。之后每次重启只重扫改动过的插件，几秒完事）",
    "p.depsIndex": "依赖索引",
    "p.depsLine": "复用 %s 个包的缓存，本次重扫 %s 个，用时 %s s",
    "p.depsWriteErr": "索引缓存写盘失败（%s）——本次结果照常，但下次启动还得重扫一遍",
    "common.dir": "目录",
    "common.itemsN": "%s 个",
    "common.inParen": "（%s 个）",
    "m.dir": "模型目录",
    "rep.done": "报告已生成：",

    "s.seg": "启动分段",
    "s.total": "合计（进程启动 → 界面就绪）",
    "s.packTable": "每个插件的启动耗时",
    "s.failed": "导入失败（IMPORT FAILED）",
    "s.degrade": "降级 / 缺失提示（不报错，但功能可能少了一部分）",
    "s.phase.pre": "启动前",
    "s.phase.imp": "导入",
    "s.totals": "日志内合计",
    "s.logInfo": "日志",
    "s.window": "启动窗口",
    "s.kProc": "进程",
    "s.kLog": "首行日志",
    "s.kServer": "服务启动",
    "s.kGui": "界面就绪",
    "common.httpNotJson": "HTTP %s（返回不是 JSON）",
    "s.logTotals": "日志内合计",
    "s.phaseCol": "阶段",
    "s.showing": "显示 %s / %s（共 %s 个权重文件，单页最多 500 行）",

    "p.filter.cand": "可禁用候选",
    "p.filter.risky": "有依赖警告",
    "p.filter.riskyDisabled": "已禁用但有牵连",
    "p.filter.enabled": "启用中",
    "p.filter.disabled": "已禁用",
    "p.filter.all": "全部",
    "p.filter.cost": "耗时 ≥ 阈值",
    "p.col.cost": "启动耗时",
    "p.col.nodes": "节点数",
    "p.col.wf": "工作流用量",
    "p.col.state": "状态",
    "p.col.risk": "风险",
    "p.col.name": "插件",
    "p.col.desc": "简介",
    "w.bucketNote": "按最后修改时间分桶 —— 点一下某个分桶可以只看这一类，再点一下取消。",
    "w.bucketHint": "点一下只看这一类",
    "w.bucketClear": "再点一下取消",
    "w.bucketOn": "当前只看：%s",
    "w.onlyBucket": "只显示高亮的内容",
    "common.more": "还有 %s 个",
    "common.less": "收起",
    "p.col.src": "耗时来源",
    "p.costDetail": "耗时来源",
    "p.refsOn": "被这些【启用中】的插件引用",
    "p.refsOff": "被这些【已禁用】的插件引用（仅参考）",
    "p.wfUsed": "用到它的工作流",
    "p.unknownUsed": "禁用后可能缺这些节点",
    "p.keepNever": "基础设施，不建议动",
    "p.note": "备注",
    "p.broad": "生态泛引用（很多包都提到它，已折叠）",
    "p.sel": "已选",
    "p.selAll": "全选当前筛选",
    "p.selNone": "清空选择",
    "p.batchDisable": "批量禁用所选",
    "p.batchEnable": "批量恢复所选",
    "p.safe": "可以清理",
    "p.risky": "有风险",
    "p.keep": "尽量别动",
    "p.noneWf": "没有任何工作流用到它",
    "p.wfCount": "%s 个工作流在用",
    "p.noRefs": "没有发现别的插件引用它",
    "p.refsCount": "%s 条引用（来自启用中的包）",
    "p.disabledHint": "已禁用",
    "p.orphanTitle": "工作流用到、但现在没注册的节点类型（可能就是你禁用了某个包）",
    "p.foldedTitle": "被很多包提到的公共依赖（折叠显示）",
    "p.stats": "%s 个包（启用 %s / 已禁用 %s）",
    "p.candHint": "候选 = 启用中 + 耗时 ≥ %s 秒 + 没有任何工作流用到它",
    "p.riskyHint": "带警告的包不是不能禁，是禁之前你得知道谁在用它 —— 点开看证据",
    "p.snapshot": "节点清单来源",
    "p.snapshotStale": "快照比源码旧，建议刷新或重启后重扫",
    "p.packsTotal": "个包 / ",
    "p.refsTotal": "条引用",

    "w.bucket": "新鲜度",
    "w.b7": "7 天内",
    "w.b30": "8–30 天",
    "w.b90": "31–90 天",
    "w.bOld": "90 天以上",
    "w.col.name": "工作流",
    "w.col.mtime": "最后改动",
    "w.col.atime": "最后读取（参考）",
    "w.col.size": "体积",
    "w.col.packs": "用到的插件",
    "w.col.missing": "缺的节点",
    "w.jsNode": "前端节点 %s 个",
    "w.filter.pack": "只看用了某个插件的工作流",
    "w.filter.missing": "只看有没注册节点的",
    "w.packsDisabled": "其中已禁用：%s",
    "w.none": "这个工作流没有识别到任何自定义插件（或全是内置节点）",
    "w.packTitle": "每个插件被哪些工作流用到",
    "w.notes": "“最后读取”来自文件系统的访问时间（Windows 上还常被杀毒/备份扫描刷新），只能当参考。",
    "w.dir": "工作流目录",
    "w.days": "%s 天",

    "m.total": "模型总量",
    "m.unref": "没被任何工作流引用",
    "m.weights": "权重文件",
    "m.files": "目录内文件总数",
    "m.tiers": "分档",
    "m.autoload": "约定自动加载目录（有什么加载什么）",
    "m.col.model": "模型",
    "m.col.type": "类型",
    "m.col.size": "体积",
    "m.col.mtime": "最后改动",
    "m.col.atime": "最后读取（参考）",
    "m.col.refs": "工作流引用",
    "m.col.tier": "归属",
    "m.col.loads": "加载记录",
    "m.filter.tier": "只看某一档",
    "m.group": "按类型分组",
    "m.groupHint": "同一个「类型」的模型放在一起，点标题能折叠这一组 —— 找某一类的时候不用在长表里翻。",
    "m.groupOn": "已按类型分成 %s 组（每组标题后面是：几个文件 · 合计体积）",
    "m.groupFlat": "现在是平铺列表（勾上「按类型分组」就按类型分组）",
    "m.groupSum": "%s 个 · %s",
    "m.neverDelete": "这里永远不会有删除按钮：只在资源管理器里定位，删不删你自己决定。",
    "m.loadHookOn": "加载记录：已开启（%s 起，共 %s 条）",
    "m.loadHookOff": "加载记录：未开启（%s）",
    "m.loadsNone": "还没有记录",
    "m.evidence": "源码证据",
    "m.refsList": "引用它的工作流",
    "m.sig": "扫描耗时 %s 秒%s",
    "m.tierHint": "used=工作流在用；auto_path/auto_name=某段源码点名了它（可能后台自动加载）；auto_dir=在约定目录里；unknown=说不清；nobody=谁都没提",
    "m.used": "工作流在用",
    "m.auto_path": "源码点名（路径）",
    "m.auto_name": "源码点名（文件名）",
    "m.auto_dir": "约定目录",
    "m.unknown": "说不清",
    "m.nobody": "谁都没提",
    "m.dirCol": "目录",
    "m.unrefIn": "其中未被引用",
    "m.wfCount": "%s 个工作流",
    "m.times": "%s 次",
    "m.yes": "是",
    "m.no": "否",

    "l.title": "每一次禁用 / 恢复都记在这里",
    "l.col.time": "时间",
    "l.col.action": "动作",
    "l.col.target": "对象",
    "l.col.result": "结果",
    "l.restore": "恢复",
    "l.empty": "还没有动作记录",
    "l.hooks": "加载钩子",
    "l.hookFile": "记录文件",
    "l.batch": "批量",
    "l.disable": "禁用",
    "l.enable": "恢复",
    "l.state": "状态",
    "l.on": "已开启",
    "l.off": "未开启",
    "l.records": "记录数",
    "l.last": "最近一次",
    "l.fail": "失败",

    "risk.title": "禁用前请确认风险",
    "risk.body": "下面这些包被【启用中的】其它插件引用，或者你的工作流正在用到。禁用后 ComfyUI 通常不会报 IMPORT FAILED，而是静默少几个节点 —— 这就是上次 ComfyUI-LTXVideo 出问题的原因。",
    "risk.batchNote": "批量禁用会一次改动多个目录。全部风险如下，确认词必须手打。",
    "risk.typeHere": "请输入确认词（区分大小写）：",
    "risk.word": "确认词",
    "risk.excludeRisky": "排除有牵连的，只禁用剩下 %s 个",
    "risk.done": "已禁用：%s",
    "risk.enableDone": "已恢复：%s",
    "risk.restart": "改完需要重启 ComfyUI 才会生效（名字在启动时才被读）。",
    "risk.riskyList": "有牵连的包（%s 个）",
    "risk.safeList": "没牵连的包（%s 个）",
    "risk.stopped": "中止：没有任何目录被改动。",
    "risk.reason": "原因",
    "risk.targets": "对象",
    "risk.safeConfirm": "确认要",
    "risk.blockedTitle": "预检没通过的项目（这些不会动）",
    "risk.skipGo": "跳过这些问题项，继续执行其余的 %s 个",
    "risk.partial": "部分完成：成功 %s 个，失败 %s 个",
  },
  en: {
    "title": "X-WIDE_plugin_model_manager",
    "sub": "What slows startup, what depends on what, what breaks if you touch it, which models are unused",
    "tab.startup": "Startup",
    "tab.packs": "Plugins",
    "tab.workflows": "Workflows",
    "tab.models": "Models",
    "tab.log": "Actions",
    "btn.help": "Help",
    "btn.report": "Write report file",
    "btn.reportView": "View report",
    "btn.reload": "Re-analyze",
    "btn.close": "Close",
    "closedTitle": "You can close this tab now",
    "closedHint": "Browsers only let script-opened tabs close themselves, so that click may not have closed this one. Press Ctrl+W, or click the tab's × - closing this page does not affect the running ComfyUI.",
    "closedBack": "Back to ComfyUI",
    "btn.open": "Open full page",
    "btn.folder": "Open folder",
    "btn.evidence": "Evidence",
    "btn.more": "Details & evidence",
    "btn.less": "Collapse",
    "btn.disable": "Disable…",
    "btn.enable": "Enable",
    "btn.refresh": "Refresh",
    "common.loading": "Analyzing… (the first full scan takes 1-2 minutes, later runs use the cache)",
    "common.error": "Error",
    "common.empty": "No data",
    "common.cancel": "Cancel",
    "common.confirm": "Confirm",
    "common.close": "Close",
    "common.name": "Name",
    "common.search": "Search name…",
    "common.seconds": "s",
    "common.enabled": "enabled",
    "common.disabled": "disabled",
    "common.notes": "Notes",
    "common.generated": "Data time",
    "common.cached": "from cache",
    "common.all": "All",
    "common.total": "Total",
    "common.count": "Count",
    "common.size": "Size",
    "common.none": "none",
    "common.warn": "Warning",
    "common.copy": "Copy",
    "common.copied": "Copied",
    "common.back": "Back",
    "common.sortBy": "Sort",
    "common.byCost": "by cost",
    "common.byName": "by name",
    "common.bySize": "by size",
    "common.byMtime": "by mtime",
    "common.pluginDirs": "plugin folders",
    "common.loadingPacks": "Analyzing plugins (the first run rebuilds the dependency index, about 2-3 minutes; progress goes to the [deps] lines in the ComfyUI log. After that each restart only rescans changed plugins - a few seconds)",
    "p.depsIndex": "Dependency index",
    "p.depsLine": "%s pack(s) reused from cache, %s rescanned this run, %s s",
    "p.depsWriteErr": "could not write the index cache (%s) - this run is fine, but the next restart will rescan everything again",
    "common.s": "s",
    "common.dir": "Folder",
    "common.itemsN": "%s items",
    "common.inParen": "(%s)",
    "m.dir": "Models folder",
    "rep.done": "Report written: ",

    "s.seg": "Startup segments",
    "s.total": "Total (process start → GUI ready)",
    "s.packTable": "Per-plugin startup cost",
    "s.failed": "IMPORT FAILED",
    "s.degrade": "Degraded / missing (no error, but features may be gone)",
    "s.phase.pre": "prestartup",
    "s.phase.imp": "import",
    "s.totals": "Log totals",
    "s.logInfo": "Log",
    "s.window": "Startup window",
    "s.kProc": "process",
    "s.kLog": "first log line",
    "s.kServer": "server up",
    "s.kGui": "GUI ready",
    "common.httpNotJson": "HTTP %s (not JSON)",
    "s.logTotals": "Log totals",
    "s.phaseCol": "Phase",
    "s.showing": "Showing %s / %s (of %s weight files, max 500 rows)",

    "p.filter.cand": "Disable candidates",
    "p.filter.risky": "Has dependents",
    "p.filter.riskyDisabled": "Disabled but referenced",
    "p.filter.enabled": "Enabled",
    "p.filter.disabled": "Disabled",
    "p.filter.all": "All",
    "p.filter.cost": "cost >= threshold",
    "p.col.cost": "Startup cost",
    "p.col.nodes": "Nodes",
    "p.col.wf": "Used by workflows",
    "p.col.state": "State",
    "p.col.risk": "Risk",
    "p.col.name": "Plugin",
    "p.col.desc": "What it does",
    "w.bucketNote": "Buckets by last-modified time - click a bucket to show only that group, click again to clear.",
    "w.bucketHint": "Click to show only this group",
    "w.bucketClear": "Click again to clear",
    "w.bucketOn": "Showing only: %s",
    "w.onlyBucket": "Show only the highlighted group",
    "common.more": "%s more",
    "common.less": "Show less",
    "p.col.src": "Cost source",
    "p.costDetail": "Cost source",
    "p.refsOn": "Referenced by these ENABLED plugins",
    "p.refsOff": "Referenced by DISABLED plugins (info only)",
    "p.wfUsed": "Workflows using it",
    "p.unknownUsed": "Node types that may disappear",
    "p.keepNever": "Infrastructure - do not touch",
    "p.note": "Note",
    "p.broad": "Ecosystem-wide references (collapsed)",
    "p.sel": "selected",
    "p.selAll": "Select all filtered",
    "p.selNone": "Clear selection",
    "p.batchDisable": "Disable selected",
    "p.batchEnable": "Enable selected",
    "p.safe": "Safe to clean",
    "p.risky": "Has risk",
    "p.keep": "Leave alone",
    "p.noneWf": "No workflow uses it",
    "p.wfCount": "used by %s workflow(s)",
    "p.noRefs": "No other plugin references it",
    "p.refsCount": "%s reference(s) from enabled packs",
    "p.disabledHint": "disabled",
    "p.orphanTitle": "Node types used by workflows but not registered now (you may have disabled a pack)",
    "p.foldedTitle": "Common dependencies mentioned by many packs (collapsed)",
    "p.stats": "%s packs (enabled %s / disabled %s)",
    "p.candHint": "Candidate = enabled + cost >= %s s + no workflow uses it",
    "p.riskyHint": "A warning does not forbid disabling - it tells you who uses it. Open the evidence.",
    "p.snapshot": "Node list source",
    "p.snapshotStale": "Snapshot older than sources - re-analyze or restart",
    "p.packsTotal": "packs / ",
    "p.refsTotal": "references",

    "w.bucket": "Freshness",
    "w.b7": "<= 7 days",
    "w.b30": "8-30 days",
    "w.b90": "31-90 days",
    "w.bOld": "> 90 days",
    "w.col.name": "Workflow",
    "w.col.mtime": "Modified",
    "w.col.atime": "Last read (ref)",
    "w.col.size": "Size",
    "w.col.packs": "Plugins used",
    "w.col.missing": "Missing nodes",
    "w.jsNode": "%s frontend node(s)",
    "w.filter.pack": "Only workflows using a plugin",
    "w.filter.missing": "Only with unregistered nodes",
    "w.packsDisabled": "disabled: %s",
    "w.none": "No custom plugin detected (or built-in nodes only)",
    "w.packTitle": "Which workflows use each plugin",
    "w.notes": "Last read is the filesystem access time (on Windows, AV/backup scans refresh it too) - reference only.",
    "w.dir": "Workflow folder",
    "w.days": "%s days",

    "m.total": "Total models",
    "m.unref": "Not referenced by any workflow",
    "m.weights": "weight files",
    "m.files": "files in the models tree",
    "m.tiers": "Tiers",
    "m.autoload": "Convention auto-load folders",
    "m.col.model": "Model",
    "m.col.type": "Type",
    "m.col.size": "Size",
    "m.col.mtime": "Modified",
    "m.col.atime": "Last read (ref)",
    "m.col.refs": "Workflow refs",
    "m.col.tier": "Tier",
    "m.col.loads": "Load records",
    "m.filter.tier": "Filter by tier",
    "m.group": "Group by type",
    "m.groupHint": "Models of the same type (unet / text_encoders / diffusion_models ...) are shown together; click a group title to fold it - no more scrolling a very long flat list.",
    "m.groupOn": "Grouped into %s type(s) (each title shows: files · total size)",
    "m.groupFlat": "Flat list right now (tick \"Group by type\" to group them)",
    "m.groupSum": "%s files · %s",
    "m.neverDelete": "There is no delete button here, by design: it only locates the file. You decide what to remove.",
    "m.loadHookOn": "Load records: on (since %s, %s rows)",
    "m.loadHookOff": "Load records: off (%s)",
    "m.loadsNone": "no record yet",
    "m.evidence": "Source evidence",
    "m.refsList": "Workflows referencing it",
    "m.sig": "scan took %s s%s",
    "m.tierHint": "used=workflow uses it; auto_path/auto_name=named in some source file (may auto-load); auto_dir=inside a convention folder; unknown=unclear; nobody=mention nowhere",
    "m.used": "used by workflow",
    "m.auto_path": "named by path",
    "m.auto_name": "named by file name",
    "m.auto_dir": "convention folder",
    "m.unknown": "unclear",
    "m.nobody": "mentioned nowhere",
    "m.dirCol": "Folder",
    "m.unrefIn": "unreferenced",
    "m.wfCount": "%s workflow(s)",
    "m.times": "%s time(s)",
    "m.yes": "yes",
    "m.no": "no",

    "l.title": "Every disable / enable is logged here",
    "l.col.time": "Time",
    "l.col.action": "Action",
    "l.col.target": "Target",
    "l.col.result": "Result",
    "l.restore": "Restore",
    "l.empty": "No actions yet",
    "l.hooks": "Load hook",
    "l.hookFile": "Record file",
    "l.batch": "batch",
    "l.disable": "disable",
    "l.enable": "enable",
    "l.state": "State",
    "l.on": "on",
    "l.off": "off",
    "l.records": "Records",
    "l.last": "Last",
    "l.fail": "failed",

    "risk.title": "Confirm before disabling",
    "risk.body": "These packs are referenced by ENABLED plugins, or your workflows use them. ComfyUI usually does NOT print IMPORT FAILED - it silently loses a few nodes. That is exactly what happened with ComfyUI-LTXVideo.",
    "risk.batchNote": "A batch disable renames several folders at once. All risks below; the confirmation phrase must be typed by hand.",
    "risk.typeHere": "Type the confirmation phrase (case sensitive):",
    "risk.word": "Phrase",
    "risk.excludeRisky": "Exclude referenced ones, disable the remaining %s",
    "risk.done": "Disabled: %s",
    "risk.enableDone": "Enabled: %s",
    "risk.restart": "ComfyUI must be restarted for this to take effect (names are read at startup).",
    "risk.riskyList": "Referenced packs (%s)",
    "risk.safeList": "Clean packs (%s)",
    "risk.stopped": "Aborted: nothing was changed.",
    "risk.reason": "Reason",
    "risk.targets": "Targets",
    "risk.safeConfirm": "Confirm",
    "risk.blockedTitle": "Failed pre-check (these will not be touched)",
    "risk.skipGo": "Skip these and run the remaining %s",
    "risk.partial": "Partly done: %s succeeded, %s failed",
  },
};

let LANG = "zh";
try {
  const saved = localStorage.getItem("xpm.lang");
  if (saved === "en" || saved === "zh") LANG = saved;
} catch (e) { /* 隐私模式等，忽略 */ }

function t(key) {
  const table = DICT[LANG] || DICT.zh;
  let s = table[key];
  if (s === undefined) s = DICT.zh[key];
  if (s === undefined) return key;
  for (let i = 1; i < arguments.length; i++) {
    s = s.replace("%s", arguments[i]);
  }
  return s;
}

/* ------------------------------------------------------------------ 小工具 */

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

function fmtBytes(b) {
  const n = Number(b) || 0;
  if (n >= 1024 * 1024 * 1024) return (n / 1073741824).toFixed(2) + " GB";
  if (n >= 1024 * 1024) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

function fmtSecs(s) {
  const n = Number(s);
  if (!isFinite(n)) return "-";
  return n.toFixed(1);
}

function badge(text, kind) {
  return el("span", "xpm-badge xpm-badge-" + (kind || "plain"), text);
}

/* 外部链接：一律新标签页打开（作者主页 / GitHub / 商店 / 反馈） */
function linkBtn(label, url) {
  const a = el("a", "xpm-btn ghost", label);
  a.href = url;
  a.target = "_blank";
  a.rel = "noreferrer noopener";
  a.title = url;
  a.style.textDecoration = "none";
  return a;
}

/* 标题下面那一排：作者 X-WIDE · v1.1.0（点开 GitHub）· GitHub 仓库 · 更新日志 · B 站主页 · 问题反馈 */
function aboutRow() {
  const row = el("div", "xpm-about");
  const sep = () => row.appendChild(document.createTextNode("  ·  "));
  row.appendChild(document.createTextNode(xt("aboutBy") + " X-WIDE"));
  sep();
  const ver = el("a", "", "v" + VERSION);
  ver.href = LINKS.repo;
  ver.target = "_blank";
  ver.rel = "noreferrer noopener";
  ver.title = LINKS.repo;
  row.appendChild(ver);
  [["aboutRepo", LINKS.repo], ["aboutChangelog", LINKS.changelog],
   ["aboutBili", LINKS.author], ["aboutIssues", LINKS.issues]].forEach((kvp) => {
    sep();
    const a = el("a", "", xt(kvp[0]));
    a.href = kvp[1];
    a.target = "_blank";
    a.rel = "noreferrer noopener";
    a.title = kvp[1];
    row.appendChild(a);
  });
  return row;
}

/*
 * 完整面板（五页签）= 一个普普通通的网页，在**浏览器新标签页**里打开。
 * 以前是在 ComfyUI 画布上盖一层整页浮层，用户反馈「占着一整页、没必要」，改掉了。
 */
function openPanel() {
  const url = PREFIX + "/ui#" + (S.tab || "startup");
  let w = null;
  try { w = window.open(url, "_blank"); } catch (e) { w = null; }
  if (w) return w;
  /* 新标签页被拦（浏览器弹窗拦截 / 非浏览器宿主）→ 至少把面板开在当前页里，别点了没反应 */
  try {
    toast("warn", xt("popoutBlocked", url));
    openBig();
  } catch (e) {
    toast("warn", xt("popoutTip"));
  }
  return null;
}

function btn(label, cls, onClick, title) {
  const b = el("button", "xpm-btn" + (cls ? " " + cls : ""), label);
  b.type = "button";
  if (title) b.title = title;
  b.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      onClick(e);
    } catch (err) {
      console.error("[xwide-plugin-manager]", err);
      toast("error", String(err && err.message ? err.message : err));
    }
  });
  return b;
}

function kv(pairs) {
  const box = el("div", "xpm-kv");
  pairs.forEach((p) => {
    if (!p) return;
    const k = p[0];
    const v = p[1];
    if (v === undefined || v === null || v === "") return;
    const row = el("div", "xpm-kv-row");
    row.appendChild(el("span", "xpm-kv-k", k));
    if (typeof v === "string" || typeof v === "number") {
      row.appendChild(el("span", "xpm-kv-v", v));
    } else {
      row.appendChild(v);
    }
    box.appendChild(row);
  });
  return box;
}

function card(title, bodyNodes, right) {
  const c = el("div", "xpm-card");
  if (title || right) {
    const h = el("div", "xpm-card-head");
    if (title) h.appendChild(el("div", "xpm-card-title", title));
    if (right) h.appendChild(right);
    c.appendChild(h);
  }
  const b = el("div", "xpm-card-body");
  (Array.isArray(bodyNodes) ? bodyNodes : [bodyNodes]).forEach((n) => {
    if (n) b.appendChild(n);
  });
  c.appendChild(b);
  return c;
}

function table(cols, rows, opts) {
  const o = opts || {};
  const wrap = el("div", "xpm-tablewrap");
  const tb = el("table", "xpm-table");
  const thead = el("thead");
  const tr = el("tr");
  cols.forEach((c) => {
    const th = el("th", c.cls || "", c.label || "");
    if (c.width) th.style.width = c.width;
    if (c.title) th.title = c.title;
    tr.appendChild(th);
  });
  thead.appendChild(tr);
  tb.appendChild(thead);
  const tbody = el("tbody");
  if (!rows.length) {
    const tr2 = el("tr");
    const td = el("td", "xpm-td-empty", o.emptyText || t("common.empty"));
    td.colSpan = Math.max(1, cols.length);
    tr2.appendChild(td);
    tbody.appendChild(tr2);
  }
  rows.forEach((r, i) => {
    const tr2 = el("tr", o.rowClass ? o.rowClass(r, i) : "");
    cols.forEach((c) => {
      const td = el("td", c.cls || "");
      let v;
      if (c.render) v = c.render(r, i);
      else v = r[c.key];
      if (v === undefined || v === null || v === "") v = "-";
      if (v instanceof Node) td.appendChild(v);
      else td.textContent = String(v);
      tr2.appendChild(td);
    });
    if (o.onClick) {
      tr2.style.cursor = "pointer";
      tr2.addEventListener("click", () => o.onClick(r, i));
    }
    tbody.appendChild(tr2);
  });
  tb.appendChild(tbody);
  wrap.appendChild(tb);
  return wrap;
}

function toast(sev, msg) {
  const kind = sev || "info";
  /* 一律自己画：样式全部内联，不吃插件样式表，也不依赖宿主前端有没有 toast API。
     之前优先把消息交给 ComfyUI 的 toast，实测真机上「生成报告文件」点了没有任何可见反馈
     （有的版本那个 API 调用成功也不显示，独立窗口里更是没有）—— 用户反馈的「点了没反应」有一半来自这里。 */
  try {
    let host = document.getElementById("xpm-toasts");
    if (!host) {
      host = el("div");
      host.id = "xpm-toasts";
      host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483100;display:flex;" +
        "flex-direction:column;gap:8px;max-width:420px";
      document.body.appendChild(host);
    }
    const tone = kind === "success" ? ["#173a24", "#7ee2a8", "#255c39"]
      : (kind === "bad" || kind === "error" ? ["#3d1d1d", "#ff9c9c", "#5c2a2a"]
        : ["#242a35", "#d6dbe6", "#333b49"]);
    const box = el("div", "xpm-toast");
    box.style.cssText = "background:" + tone[0] + ";color:" + tone[1] + ";border:1px solid " + tone[2] +
      ";border-radius:9px;padding:9px 12px;font-size:14px;line-height:1.5;box-shadow:0 6px 22px rgba(0,0,0,.45)";
    box.appendChild(el("div", "", t("title")));
    box.appendChild(el("div", "", String(msg)));
    host.appendChild(box);
    setTimeout(() => {
      try {
        box.remove();
      } catch (e) { /* 忽略 */ }
    }, 6000);
  } catch (e) {
    console.log("[xwide-plugin-manager][" + kind + "]", msg);
  }
}

function showModal(title, buildBody, opts) {
  const o = opts || {};
  const back = el("div", "xpm-modal-back");
  const box = el("div", "xpm-modal");
  const head = el("div", "xpm-modal-head");
  head.appendChild(el("div", "xpm-modal-title", title));
  const closeBtn = btn(t("btn.close"), "ghost", () => back.remove());
  head.appendChild(closeBtn);
  const bodyNode = el("div", "xpm-modal-body");
  buildBody(bodyNode, () => back.remove());
  box.appendChild(head);
  box.appendChild(bodyNode);
  if (o.footer) {
    const foot = el("div", "xpm-modal-foot");
    o.footer(foot, () => back.remove());
    box.appendChild(foot);
  }
  /* 关键样式内联写死：万一插件样式表没注入、或者被宿主的 CSS 盖掉，
     弹窗也必须是「盖在最上面的一层」——真机实测过「弹窗在 DOM 里、内容齐全，
     但排在文档流底部、被 ComfyUI 画布盖住」，用户看到的就是点了没反应。 */
  back.style.cssText = "position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.62);" +
    "display:flex;align-items:center;justify-content:center";
  back.appendChild(box);
  back.addEventListener("click", (e) => {
    if (e.target === back) back.remove();
  });
  document.body.appendChild(back);
  return { back: back, box: box, body: bodyNode, close: () => back.remove() };
}

/* 用自己的确认窗替掉 window.confirm：原生弹窗没法排版，也没法把关键约束标色、放大字号。
   返回 Promise<boolean>：只有点了「确定」才是 true。 */
function confirmModal(title, lines, okLabel, danger) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (v) => { if (!settled) { settled = true; resolve(v); } };
    showModal(title, (body) => {
      (lines || []).forEach((ln) => {
        if (!ln) return;
        if (ln.kind === "warn") body.appendChild(el("div", "xpm-warnbox", ln.text));
        else if (ln.kind === "list") {
          const ul = el("ul", "xpm-list");
          (ln.items || []).forEach((x) => ul.appendChild(el("li", "", x)));
          body.appendChild(ul);
        } else body.appendChild(el("div", "xpm-note", ln.text !== undefined ? ln.text : String(ln)));
      });
    }, {
      footer: (foot, close) => {
        foot.appendChild(btn(t("common.cancel"), "ghost", () => { finish(false); close(); }));
        foot.appendChild(btn(okLabel || t("common.confirm"), danger ? "danger" : "primary",
          () => { finish(true); close(); }));
      },
    });
  });
}

/* 把纯文本说明/报告排成「小节标题 + 列表」，而不是整段塞进 <pre>：
   使用说明和报告原来信息堆在一起，用户反馈看不下去（图8）。 */
function richBlocks(text) {
  const out = [];
  let cur = null;
  String(text == null ? "" : text).split(/\r?\n/).forEach((raw) => {
    const s = raw.replace(/\s+$/, "");
    const h = s.match(/^\s*(?:#{1,6}\s+(.+)|【(.+)】)\s*$/);
    if (h) {
      cur = { title: (h[1] || h[2]).trim(), items: [] };
      out.push(cur);
      return;
    }
    if (!s.trim()) return;
    if (!cur) {
      cur = { title: "", items: [] };
      out.push(cur);
    }
    const li = s.match(/^\s*(?:[·•\-*]|\d+[.)])\s+(.*)$/);
    if (li) cur.items.push(li[1].trim());
    else if (cur.items.length && /^\s{2,}/.test(raw)) cur.items[cur.items.length - 1] += " " + s.trim();
    else cur.items.push({ para: true, text: s.trim() });
  });
  return out;
}

function showRichModal(title, text) {
  showModal(title, (body) => {
    richBlocks(text).forEach((sec) => {
      if (sec.title) body.appendChild(el("div", "xpm-rich-title", sec.title));
      const ul = el("ul", "xpm-list");
      let used = false;
      sec.items.forEach((it) => {
        if (it && typeof it === "object") {
          body.appendChild(el("div", "xpm-note", it.text));
          return;
        }
        ul.appendChild(el("li", "", it));
        used = true;
      });
      if (used) body.appendChild(ul);
    });
  });
}

function showTextModal(title, text) {
  showModal(title, (bodyNode) => {
    bodyNode.appendChild(el("pre", "xpm-pre", text));
    const bar = el("div", "xpm-row");
    bar.appendChild(btn(t("common.copy"), "", () => {
      try {
        navigator.clipboard.writeText(text);
        toast("success", t("common.copied"));
      } catch (e) {
        toast("warn", String(e));
      }
    }));
    bodyNode.appendChild(bar);
  });
}

async function apiGet(path) {
  const r = await fetch(PREFIX + path, { headers: { "Accept": "application/json" } });
  let j = null;
  try {
    j = await r.json();
  } catch (e) {
    throw new Error(t("common.httpNotJson", r.status));
  }
  if (!r.ok || !j || j.ok === false) {
    throw new Error((j && j.error) || ("HTTP " + r.status));
  }
  return j;
}

async function apiPost(path, payload) {
  const r = await fetch(PREFIX + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  let j = null;
  try {
    j = await r.json();
  } catch (e) {
    throw new Error(t("common.httpNotJson", r.status));
  }
  if (!j) throw new Error("HTTP " + r.status);
  if (j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

/* ------------------------------------------------------------------ 状态 */

const S = {
  tab: "startup",
  data: {},
  loaded: {},
  loading: {},
  error: {},
  sel: new Set(),
  filter: {
    packs: "cand",
    packs_q: "",
    wfPack: "",
    wfMissing: false,
    wfBucket: "",          /* 新鲜度分桶筛选："" / d7 / d30 / b90 / older */
    wfOnly: true,          /* 「只显示高亮的内容」勾选状态 */
    wf_q: "",
    models_q: "",
    models_tier: "",
    models_group: true,    /* 模型表按「类型」分组（用户要求；可取消勾选回到平铺） */
  },
  sort: { packs: "cost", models: "size" },
  expanded: new Set(),
  modelsFolded: new Set(), /* 模型页被折叠起来的分组（类型名） */
  root: null,
  autoVisit: false,      /* 用户刚进入「插件分析」页 → 允许自动处理跑一次 */
  autoBusy: false,
};

function setLang(next) {
  LANG = next === "en" ? "en" : "zh";
  try {
    localStorage.setItem("xpm.lang", LANG);
  } catch (e) { /* 忽略 */ }
  if (S.root) {
    S.root.remove();
    S.root = null;
  }
  openBig();
}

/* ------------------------------------------------------------------ 大页面 */

function injectStyle() {
  if (document.getElementById("xpm-style")) return;
  const css = [
    ".xpm-root{position:fixed;inset:0;z-index:12000;background:#14161a;color:#e6e8ee;",
    "font:14px/1.55 'Microsoft YaHei UI','Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column}",
    /* 独立窗口顶部的提示条（外壳页面里那条会被 fixed 根节点盖住，所以画在这里） */
    ".xpm-satip{padding:7px 16px;font-size:12px;color:#8b93a7;background:#181b21;border-bottom:1px solid #2a2f3a}",
    ".xpm-head{padding:12px 18px;border-bottom:1px solid #2a2f3a;display:flex;align-items:center;gap:18px;flex-wrap:wrap;background:#181b21}",
    ".xpm-brand{font-size:22px;font-weight:700;letter-spacing:.3px}",
    ".xpm-ver{font-size:12.5px;font-weight:600;color:#9ec1ff;background:#1d2635;border:1px solid #2f3f5c;border-radius:999px;padding:2px 9px;letter-spacing:.2px}",
    ".xpm-head-brand{display:flex;flex-direction:column;gap:3px;flex:0 0 auto}",
    ".xpm-brand-line{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}",
    ".xpm-head-about{flex:1 1 auto;min-width:220px}",
    ".xpm-head-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;margin-left:auto}",
    ".xpm-head-actions .xpm-btn{padding:7px 13px;font-size:14.5px}",
    ".xpm-sub{color:#8b93a7;font-size:12.5px}",
    /* 标题下面那一排：作者 / 版本（点开 GitHub）/ 更新日志 / B 站 / 反馈 */
    ".xpm-about{color:#8b93a7;font-size:12px;margin-top:4px;line-height:1.7}",
    ".xpm-about a{color:#7fb2ff;text-decoration:none}",
    ".xpm-about a:hover{text-decoration:underline}",
    ".xpm-spacer{flex:1}",
    ".xpm-tabs{display:flex;gap:6px;padding:8px 16px 0;border-bottom:1px solid #2a2f3a;background:#181b21;flex-wrap:wrap}",
    ".xpm-tab{padding:10px 18px;border:1px solid transparent;border-bottom:none;border-radius:8px 8px 0 0;",
    "background:transparent;color:#9aa2b6;cursor:pointer;font-size:16px}",
    ".xpm-tab.on{background:#14161a;color:#fff;border-color:#2a2f3a;font-weight:600}",
    ".xpm-tab:hover{color:#fff}",
    ".xpm-body{flex:1;overflow:auto;padding:16px}",
    ".xpm-btn{background:#242a35;color:#e6e8ee;border:1px solid #333b49;border-radius:7px;padding:7px 13px;",
    "cursor:pointer;font-size:14px}",
    ".xpm-btn:hover{background:#2d3542}",
    ".xpm-btn.primary{background:#2a5bd7;border-color:#2a5bd7;color:#fff}",
    ".xpm-btn.danger{background:#8c2f2f;border-color:#a33a3a;color:#fff}",
    ".xpm-btn.ghost{background:transparent}",
    ".xpm-btn:disabled{opacity:.45;cursor:not-allowed}",
    ".xpm-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}",
    ".xpm-card{background:#1b1f26;border:1px solid #2a2f3a;border-radius:10px;margin-bottom:18px}",
    ".xpm-card-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #262c36}",
    ".xpm-card-title{font-size:19px;font-weight:600}",
    ".xpm-card-body{padding:12px 14px}",
    ".xpm-kv{display:flex;flex-direction:column;gap:5px}",
    ".xpm-kv-row{display:flex;gap:10px;align-items:baseline}",
    ".xpm-kv-k{color:#8b93a7;min-width:150px;font-size:14px}",
    ".xpm-kv-v{font-size:15px}",
    ".xpm-tablewrap{overflow:auto;border:1px solid #262c36;border-radius:8px}",
    ".xpm-table{border-collapse:collapse;width:100%;font-size:14.5px}",
    ".xpm-table th{position:sticky;top:0;background:#20252e;text-align:left;padding:9px 10px;",
    "border-bottom:1px solid #2f3644;white-space:nowrap;font-weight:600;color:#c3cad9}",
    ".xpm-table td{padding:8px 10px;border-bottom:1px solid #232831;vertical-align:top}",
    ".xpm-table tr:hover td{background:#1f242c}",
    ".xpm-td-empty{color:#8b93a7;text-align:center;padding:18px}",
    ".xpm-tr-warn td{background:#2a2318}",
    ".xpm-tr-bad td{background:#2c1c1c}",
    ".xpm-badge{display:inline-block;border-radius:6px;padding:3px 9px;font-size:13.5px;border:1px solid transparent}",
    ".xpm-legend .xpm-badge{font-size:15px;padding:4px 10px}",
    ".xpm-bucket{cursor:pointer}",
    ".xpm-bucket.on{outline:2px solid #4a8cff;outline-offset:1px}",
    ".xpm-desc{color:#9aa2b6;font-size:13.5px;line-height:1.6;display:-webkit-box;-webkit-line-clamp:2;" +
      "-webkit-box-orient:vertical;overflow:hidden;max-width:340px;word-break:break-word}",
    ".xpm-chip{display:inline-block;background:#20252e;border:1px solid #2f3644;border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0;font-size:13px;color:#cdd3e0}",
    ".xpm-badge-good{background:#173a24;color:#7ee2a8;border-color:#255c39}",
    ".xpm-badge-warn{background:#3d3116;color:#f2c66d;border-color:#5c4a1e}",
    ".xpm-badge-bad{background:#3d1d1d;color:#ff9c9c;border-color:#5c2a2a}",
    ".xpm-badge-info{background:#1b2f47;color:#8fc4ff;border-color:#274866}",
    ".xpm-badge-plain{background:#242a35;color:#aab2c4;border-color:#333b49}",
    ".xpm-note{color:#9aa2b6;font-size:14.5px;margin:5px 0}",
    ".xpm-warnbox-inline{max-width:860px;display:flex;gap:8px;align-items:flex-start;line-height:1.7}",
    ".xpm-warnbox{background:#2a2318;border:1px solid #5c4a1e;color:#f2c66d;border-radius:8px;padding:9px 12px;margin:9px 0;font-size:14px}",
    ".xpm-errbox{background:#2c1c1c;border:1px solid #5c2a2a;color:#ff9c9c;border-radius:8px;padding:9px 12px;margin:9px 0;font-size:14px}",
    ".xpm-input{background:#12151a;border:1px solid #333b49;color:#e6e8ee;border-radius:7px;padding:7px 10px;font-size:14px;min-width:170px}",
    ".xpm-select{background:#12151a;border:1px solid #333b49;color:#e6e8ee;border-radius:7px;padding:7px 9px;font-size:14px}",
    ".xpm-seg{display:flex;gap:5px;flex-wrap:wrap}",
    ".xpm-seg button{background:#1f242c;border:1px solid #333b49;color:#9aa2b6;border-radius:7px;padding:6px 12px;cursor:pointer;font-size:14px}",
    ".xpm-seg button.on{background:#2a5bd7;border-color:#2a5bd7;color:#fff}",
    ".xpm-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}",
    ".xpm-bar{display:flex;height:26px;border-radius:5px;overflow:hidden;border:1px solid #2a2f3a;margin:8px 0}",
    ".xpm-bar span{display:block;height:100%}",
    ".xpm-details{background:#171b21;border:1px dashed #2f3644;border-radius:8px;padding:10px 12px;margin:8px 0;font-size:14px}",
    ".xpm-code{font-family:Consolas,'Courier New',monospace;font-size:13px;color:#9fd0ff;word-break:break-all}",
    ".xpm-pre{max-height:60vh;overflow:auto;white-space:pre-wrap;font-size:13px;color:#cfd6e4}",
    ".xpm-modal-back{position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:13000;display:flex;align-items:center;justify-content:center}",
    ".xpm-modal{background:#1b1f26;border:1px solid #333b49;border-radius:12px;min-width:560px;max-width:min(1020px,92vw);max-height:88vh;display:flex;flex-direction:column}",
    ".xpm-modal-head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #262c36}",
    ".xpm-modal-title{font-size:18px;font-weight:600;flex:1}",
    ".xpm-modal-body{padding:14px 16px;overflow:auto;font-size:15.5px;line-height:1.75}",
    ".xpm-modal-foot{padding:12px 16px;border-top:1px solid #262c36;display:flex;gap:10px;justify-content:flex-end}",
    ".xpm-list{margin:6px 0 6px 18px;padding:0}",
    ".xpm-list li{margin:3px 0}",
    ".xpm-clickable{cursor:pointer;color:#8fc4ff}",
    ".xpm-big{font-size:32px;font-weight:700;line-height:1.15}",
    ".xpm-biglabel{font-size:20px;font-weight:600;color:#e6e8ee}",
    /* 侧边栏四组分区：品牌 / 自动处理 / 常用操作 / 作者与链接 */
    ".xpm-side{display:flex;flex-direction:column}",
    ".xpm-side-brand{display:flex;flex-direction:column;align-items:center;text-align:center;gap:6px;padding:4px 0 14px}",
    /* 品牌图标：用作者自己的 X-WIDE 横版 logo（白底卡片），宽度自适应侧边栏 */
    ".xpm-side-logo{width:212px;max-width:100%;height:auto;background:#fff;border-radius:14px;padding:6px 8px;box-sizing:border-box;margin-bottom:6px}",
    ".xpm-head-logo{height:28px;width:auto;background:#fff;border-radius:7px;padding:2px 5px;box-sizing:border-box}",
    /* 版本 / 开源协议 两个小徽标（用户要求：品牌区加入版本号与开源协议） */
    ".xpm-side-meta{display:flex;gap:7px;align-items:center;justify-content:center;flex-wrap:wrap;margin-top:6px}",
    ".xpm-side-meta .xpm-badge{font-size:13px;padding:3px 9px}",
    ".xpm-lic{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:600;color:#9ec1ff;background:#1d2635;border:1px solid #2f3f5c;border-radius:999px;padding:3px 10px;text-decoration:none;cursor:pointer}",
    ".xpm-lic:hover{background:#243149}",
    /* 免责声明：小字、左对齐、不抢视觉 */
    ".xpm-side-disc{font-size:12.5px;line-height:1.7;color:#8d94a6;text-align:left;margin-top:9px;border-top:1px dashed #2a3040;padding-top:8px}",
    ".xpm-tierbtn{background:none;border:0;padding:0;margin:0;cursor:pointer;font:inherit;line-height:1}",
    ".xpm-tierbtn .xpm-badge{opacity:.75}",
    ".xpm-tierbtn:hover .xpm-badge{opacity:1}",
    ".xpm-tierbtn.on .xpm-badge{opacity:1;outline:2px solid #5b95ff;outline-offset:1px}",
    ".xpm-status{margin:8px 0 0}",
    ".xpm-side-title{font-size:20px;font-weight:700;line-height:1.35;color:#e6e8ee;word-break:break-word}",
    ".xpm-side-gtitle{font-size:15px;font-weight:600;color:#c9cfdd;margin:0 0 8px}",
    ".xpm-rich-title{font-size:16.5px;font-weight:600;color:#dbe1ee;margin:16px 0 6px}",
    ".xpm-rich-title:first-child{margin-top:0}",
    ".xpm-side-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}",
    ".xpm-side-row:last-child{margin-bottom:0}",
    ".xpm-side .xpm-btn{padding:8px 12px;font-size:14.5px}",
    /* 副标题（作者要求：加大加粗、带颜色，放在图标下面一眼能看到） */
    ".xpm-side-sub{font-size:15.5px;font-weight:700;line-height:1.7;color:#ff7ab8;margin-top:2px;letter-spacing:.2px}",
    ".xpm-sub{font-size:14.5px;font-weight:700;color:#ff7ab8;letter-spacing:.2px}",
    /* 模型页按类型分组：一组一个可折叠块 */
    ".xpm-group{margin:10px 0;border:1px solid #262c3a;border-radius:10px;overflow:hidden;background:#171b23}",
    ".xpm-group>summary{cursor:pointer;padding:10px 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;user-select:none}",
    ".xpm-group>summary:hover{background:#1c2130}",
    ".xpm-group-name{font-weight:700;font-size:15.5px;color:#e6e8ee}",
    /* 「执行中」提示：转圈 + 已等待秒数，长任务也不会看着像没反应 */
    ".xpm-busy{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:9px 12px;margin:8px 0;font-size:15px;" +
      "background:#1b2233;border:1px solid #2b3653;border-radius:9px}",
    ".xpm-spin{display:inline-block;font-size:17px;color:#5b95ff}",
    ".xpm-btn:disabled,.xpm-btn[disabled]{opacity:.5;cursor:not-allowed}",
    ".xpm-wide{width:100%;justify-content:center}",
    ".xpm-third{flex:1 1 0;min-width:0;justify-content:center}",
  ].join("");
  const st = el("style");
  st.id = "xpm-style";
  st.textContent = css;
  document.head.appendChild(st);
}

/* 「关闭」按钮：独立窗口里就真的把标签页关掉；关不掉（这个标签页不是脚本打开的）时给一句能照做的提示，
   而不是像以前那样只把 DOM 移除、留一个空白页给用户（用户反馈：点完关闭是个空标签页）。 */
function closePanel() {
  if (!STANDALONE) {
    if (S.root) {
      S.root.remove();
      S.root = null;
    }
    return;
  }
  try { window.close(); } catch (e) { /* 关不掉就靠下面的提示 */ }
  setTimeout(() => {
    if (document.hidden) return;
    try {
      showModal(xt("closedTitle"), (b) => {
        b.appendChild(el("div", "xpm-note", xt("closedHint")));
        const row = el("div", "xpm-row");
        row.appendChild(btn(xt("closedBack"), "primary", () => {
          try { location.href = "/"; } catch (e) { /* 忽略 */ }
        }));
        b.appendChild(row);
      });
    } catch (e) { /* 忽略 */ }
  }, 400);
}

function openBig() {
  injectStyle();
  if (S.root) {
    S.root.remove();
    S.root = null;
  }
  const root = el("div", "xpm-root");
  /* 根节点同样内联关键样式：任何情况下都要盖住宿主界面（见 showModal 里的同款说明） */
  root.style.cssText = "position:fixed;inset:0;z-index:2147482000;background:#14161a;color:#e6e8ee;" +
    "display:flex;flex-direction:column";

  /* 头部三段式：左＝标题组（名字 + 版本徽标 + 一句话），中＝作者信息排，右＝按钮组。
     原来六七个按钮和标题挤成一行、没有主次（用户反馈「不直观」，见 图9）。 */
  const head = el("div", "xpm-head");
  const brand = el("div", "xpm-head-brand");
  const brandLine = el("div", "xpm-brand-line");
  try {
    /* 页眉也带上作者自己的 X-WIDE logo（与侧边栏同一个文件，取不到就不显示） */
    const hl = el("img", "xpm-head-logo");
    hl.src = PREFIX + "/web/logo_xwide.png";
    hl.alt = "X-WIDE";
    hl.addEventListener("error", () => { try { hl.remove(); } catch (e) {} });
    brandLine.appendChild(hl);
  } catch (e) { /* 忽略：没有 logo 也要能用 */ }
  brandLine.appendChild(el("span", "xpm-brand", t("title")));
  brandLine.appendChild(el("span", "xpm-ver", "v" + VERSION));
  try {
    /* 开源协议徽标（点开是仓库里的 LICENSE） */
    const lic = el("a", "xpm-lic", "⚖ " + xt("licenseName"));
    lic.href = LINKS.license;
    lic.target = "_blank";
    lic.rel = "noreferrer noopener";
    lic.title = xt("licenseTip");
    brandLine.appendChild(lic);
  } catch (e) { /* 忽略 */ }
  brand.appendChild(brandLine);
  brand.appendChild(el("div", "xpm-sub", t("sub")));
  head.appendChild(brand);
  const headAbout = el("div", "xpm-head-about");
  headAbout.appendChild(aboutRow());
  head.appendChild(headAbout);
  const headActions = el("div", "xpm-head-actions");
  headActions.appendChild(regReloadBtn(btn(t("btn.reload"), "", (ev) => reloadWithFeedback(S.tab, ev && ev.currentTarget))));
  headActions.appendChild(btn(t("btn.report"), "", genReport));
  headActions.appendChild(btn(t("btn.reportView"), "", viewReport));
  headActions.appendChild(btn(t("btn.help"), "", showHelp));
  if (!STANDALONE) {
    /* 完整面板在浏览器新标签页里打开（同一个前端脚本 + /ui 空壳页），可拖到第二台显示器 */
    headActions.appendChild(btn(xt("popout"), "ghost", openPanel, xt("popoutTip")));
  }
  headActions.appendChild(btn(LANG === "zh" ? "English" : "中文", "ghost", () => setLang(LANG === "zh" ? "en" : "zh")));
  headActions.appendChild(btn(t("btn.close"), "ghost", closePanel));
  head.appendChild(headActions);
  /* 独立窗口顶部的提示条：面板根节点是 position:fixed;inset:0，
     所以这条必须画在面板里面 —— 放在外壳页面里会被整个盖住（实测看不到）。
     location 也要防着拿不到（Node / worker 之类的宿主里没有它，不该把整个界面带崩）。 */
  if (STANDALONE) {
    let org = "";
    try { org = (typeof location !== "undefined" && location.origin) || ""; } catch (e) { org = ""; }
    root.appendChild(el("div", "xpm-satip", org ? xt("saTip", org) : xt("saTipNoUrl")));
  }
  root.appendChild(head);

  /* 页签 */
  const tabs = el("div", "xpm-tabs");
  const TAB_DEFS = [
    ["startup", t("tab.startup")],
    ["packs", t("tab.packs")],
    ["workflows", t("tab.workflows")],
    ["models", t("tab.models")],
    ["log", t("tab.log")],
  ];
  /* 深链：#packs / #workflows / #models / #log / #startup —— 可以直接收藏、也能给截图脚本用 */
  const wantTab = (function () {
    try { return (location.hash || "").replace(/^#/, "").trim().toLowerCase(); }
    catch (e) { return ""; }
  })();
  if (wantTab && TAB_DEFS.some((d) => d[0] === wantTab)) S.tab = wantTab;
  if (S.tab === "packs") S.autoVisit = true;
  TAB_DEFS.forEach((def) => {
    const id = def[0];
    const label = def[1];
    const b = el("button", "xpm-tab" + (S.tab === id ? " on" : ""), label);
    b.type = "button";
    b.addEventListener("click", () => {
      S.tab = id;
      if (id === "packs") S.autoVisit = true;   /* 进入本页才允许「自动处理」自动跑一次 */
      Array.prototype.forEach.call(tabs.children, (c) => c.classList.remove("on"));
      b.classList.add("on");
      /* 只有独立窗口才去写地址栏：主界面那页是 ComfyUI 的前端，别动它的 URL */
      if (STANDALONE) { try { history.replaceState(null, "", "#" + id); } catch (e) { /* 忽略 */ } }
      renderActive();
    });
    tabs.appendChild(b);
  });
  root.appendChild(tabs);

  /* 页眉下面的状态行：「重新分析」跑的时候在这里显示转圈 + 已等待秒数
     （用户反馈：点「重新分析」没有任何提示，不知道点没点上 —— 图3） */
  S.statusHost = el("div", "xpm-status");
  root.appendChild(S.statusHost);

  const bodyNode = el("div", "xpm-body");
  bodyNode.id = "xpm-body";
  root.appendChild(bodyNode);

  document.body.appendChild(root);
  S.root = root;
  renderActive();
}

function bodyEl() {
  /* 按 class 从本页面自己的根节点往下找。
     不要用 getElementById("xpm-body")：独立窗口的外壳页面里曾经也有一个同名容器，
     两个同名 id 会让页面内容渲染到外壳那一层去（外壳那个现在改名叫 xpm-shell-body）。 */
  const root = S.root || document;
  try {
    const hit = root.querySelector ? root.querySelector(".xpm-body") : null;
    if (hit) return hit;
  } catch (e) { /* 落到下面的兜底 */ }
  return document.getElementById("xpm-body");
}

function renderActive() {
  const bodyNode = bodyEl();
  if (!bodyNode) return;
  clear(bodyNode);

  const page = S.tab;
  if (S.error[page]) {
    bodyNode.appendChild(el("div", "xpm-errbox", t("common.error") + "：" + S.error[page]));
    bodyNode.appendChild(regReloadBtn(btn(t("btn.reload"), "", (ev) => reloadWithFeedback(page, ev && ev.currentTarget))));
    return;
  }
  if (!S.loaded[page]) {
    bodyNode.appendChild(el("div", "xpm-note", t(page === "packs" ? "common.loadingPacks" : "common.loading")));
    loadTab(page, false);
    return;
  }
  const d = S.data[page];
  if (page === "startup") pageStartup(bodyNode, d);
  else if (page === "packs") pagePacks(bodyNode, d);
  else if (page === "workflows") pageWorkflows(bodyNode, d);
  else if (page === "models") pageModels(bodyNode, d);
  else if (page === "log") pageLog(bodyNode, d);
}

async function loadTab(page, force) {
  if (S.loading[page]) return;
  S.loading[page] = true;
  S.error[page] = null;
  try {
    let url = null;
    if (page === "packs") url = "/analyze?force=" + (force ? 1 : 0);
    else if (page === "startup") url = "/startup";
    else if (page === "workflows") url = "/workflows";
    else if (page === "models") url = "/models?force=" + (force ? 1 : 0);
    else if (page === "log") {
      const results = await Promise.all([apiGet("/log?limit=300"), apiGet("/hooks")]);
      S.data.log = { items: (results[0] && results[0].log) || [], hook: results[1].hook || {}, file: results[1].file };
      S.loaded.log = true;
      S.loading.log = false;
      if (S.tab === "log") renderActive();
      return;
    }
    const res = await apiGet(url);
    S.data[page] = res.data || res;
    S.loaded[page] = true;
    S.loading[page] = false;
    if (S.tab === page) renderActive();
  } catch (e) {
    S.loading[page] = false;
    S.error[page] = String(e && e.message ? e.message : e);
    if (S.tab === page) renderActive();
  }
}

/* 手动「重新分析」：立刻给反馈 —— 按钮锁住、页眉下面转圈计时、跑完报用时。
   为什么单独写一层：loadTab 会自己吞掉错误（把错误画到页面上），
   点按钮的人看不到「开始了没有」，也看不到「跑完了没有」（用户图3）。 */
let _reloadBusy = false;
/* 登记所有「重新分析」按钮：真浏览器里 ev.currentTarget 就够了，
   但独立窗口 / 老前端的事件对象不一定带 currentTarget，所以留一张登记表兜底。 */
function regReloadBtn(b) {
  if (!b) return b;
  S.reloadBtns = (S.reloadBtns || []).filter((x) => x && x.parentNode);
  S.reloadBtns.push(b);
  return b;
}
async function reloadWithFeedback(page, btnEl) {
  if (_reloadBusy) { toast("warn", xt("reloadBusy")); return; }
  _reloadBusy = true;
  const t0 = Date.now();
  let stop = null;
  try { if (S.statusHost) stop = startBusy(S.statusHost, xt("reloadStart")); } catch (e) { stop = null; }
  const targets = [];
  if (btnEl) targets.push(btnEl);
  (S.reloadBtns || []).forEach((b) => { if (targets.indexOf(b) < 0) targets.push(b); });
  targets.forEach((b) => { try { b.disabled = true; } catch (e) { /* 忽略 */ } });
  toast("info", xt("reloadStart"));
  try {
    await loadTab(page, true);
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    if (S.error[page]) toast("error", xt("reloadFail", S.error[page]));
    else toast("success", xt("reloadDone", secs));
  } catch (e) {
    toast("error", xt("reloadFail", strOf(e)));
  } finally {
    _reloadBusy = false;
    targets.forEach((b) => { try { b.disabled = false; } catch (e) { /* 忽略 */ } });
    if (stop) { try { stop(); } catch (e) { /* 忽略 */ } }
  }
}

async function genReport() {
  toast("info", t("common.loading"));
  try {
    const j = await apiPost("/report", {});
    toast("success", t("rep.done") + (j.path || ""));
  } catch (e) {
    toast("error", String(e && e.message ? e.message : e));
  }
}

async function viewReport() {
  try {
    const j = await apiGet("/report");
    showRichModal(t("btn.reportView"), j.text || "");
  } catch (e) {
    toast("warn", String(e && e.message ? e.message : e));
  }
}

function showHelp() {
  const zh = [
    "这个页面只做三件事：看清、判断、留痕。",
    "",
    "【五个页签】",
    "· 启动体检：进程启动 → 界面就绪的总时长，以及是哪些插件花掉的。",
    "· 插件分析：每个包的启动耗时、注册了多少节点、被几个工作流用到、谁在引用它。",
    "    绿色“可以清理” = 耗时超过阈值，而且没有任何工作流用到它；",
    "    黄色“有风险” = 还有别的插件在引用它，或者你的工作流在用；",
    "    红色“尽量别动” = 基础设施（例如 ComfyUI-Manager），或几十个包都依赖它。",
    "· 工作流分析：每个工作流最后一次改动/读取是什么时候、用了哪些插件、有没有已经禁用的插件。",
    "· 模型分析：680 GB 里哪些没有被任何工作流引用，再看它们是被源码点名、还是在约定目录里、还是谁都没提。",
    "· 动作记录：每次禁用/恢复都在这里，可以一键恢复。",
    "",
    "【安全边界】",
    "· 只有“禁用/恢复”会改动文件系统：把 custom_nodes\\<包> 改名成 <包>.disabled（ComfyUI 自己的约定）。",
    "· 不删文件、不动 pip 包、绝不动模型；模型页只有“打开文件夹”。",
    "· 禁用前会把风险列出来，有牵连就必须手打确认词；批量禁用同样要手打。",
    "· 目录改名要重启 ComfyUI 才生效。",
    "",
    "【自动处理（可选，默认关）】",
    "· 开关在**侧边栏**里（左侧 X-WIDE 图标）和“插件分析”页顶部各有一个，是同一个设置。",
    "· 勾上之后：每次进入“插件分析”页，都会按规则扫描，并自动禁用符合条件的包",
    "    （两种模式：只挑“从没用过”，或“从没用过 + 超过 N 天没碰过”）。",
    "    侧边栏里只是开关和按钮，不会因为你点开侧边栏就动手。",
    "· 服务端硬保护：一次最多 12 个、且不超过已启用包总数的一半；源码 3 天内动过的、",
    "    被别的插件真正 import 的、固定名单里的，一律不动。",
    "· 执行前可以先点“先看计划”（不改动任何东西）；执行时要手打确认词；跑完弹结果窗，带一键恢复。",
    "· 不勾选就只是“你点按钮才扫描”，而且本插件没有 prestartup 脚本，不会拖慢启动。",
    "",
    "【侧边栏与完整面板】",
    "· 侧边栏（左侧 X-WIDE 图标）里直接就有：自动处理的开关与三个按钮、生成报告，",
    "    以及 GitHub 与 B 站两个入口。",
    "· “打开完整面板”会在**浏览器新标签页**里打开五页签界面（不盖住 ComfyUI 画布）；",
    "    也可以直接访问 http://127.0.0.1:8188/xwide/plugin-manager/ui （端口按你自己的 ComfyUI 改）。",
    "· 完整面板标题下面那一排是作者信息：作者 X-WIDE、版本号（点开 GitHub 仓库）、GitHub 仓库、",
    "    更新日志、B 站主页、问题反馈。右上角的 English / 中文 切换会记住你的选择。",
    "· 那个页面不加载 ComfyUI 前端，只有本插件自己的界面，可以拖到第二个显示器上常驻，截图、对照都方便。",
    "",
    "【模型“有没有被用过”怎么判断】",
    "· 静态：工作流里出现过文件名 = 用过（并显示引用次数）。",
    "· 源码：某段代码点名了这个文件 = 可能后台自动加载（会给出 文件:行号）。",
    "· 动态：装上“加载钩子”以后，真正被加载过的会记时间与次数（只记录、不拦截）。",
    "· 文件系统的“最后读取”时间会被杀毒/备份/网盘扫描刷新（Windows 上尤其常见），只能当参考。",
  ].join("\n");
  const en = [
    "This page only does three things: show, judge, keep a record.",
    "",
    "[Five tabs]",
    "· Startup: total time from process start to GUI ready, and which plugins spent it.",
    "· Plugins: startup cost, registered node count, workflow usage, who references it.",
    "    green = over the cost threshold and no workflow uses it;",
    "    amber = other plugins or workflows still use it;",
    "    red = infrastructure, or dozens of packs depend on it.",
    "· Workflows: last modified/read, plugins used, and whether any used plugin is disabled.",
    "· Models: which of the 680 GB no workflow references - and whether source code names them.",
    "· Actions: every disable/enable, with one-click restore.",
    "",
    "[Safety]",
    "· Only disable/enable touches the filesystem, by renaming custom_nodes\\<pack> to <pack>.disabled.",
    "· No deleting, no pip changes, never models; the models page only opens folders.",
    "· Risks are listed first; anything referenced requires a typed confirmation phrase.",
    "· A restart is required for renames to take effect.",
    "",
    "[Autopilot (optional, off by default)]",
    "· The switch lives in the **sidebar** (the X-WIDE icon on the left) and at the top of the Plugins tab -",
    "    it is the same setting in both places.",
    "· Tick it and every visit to the Plugins tab scans and disables the packs that match",
    "    (either \"never used\" or \"never used + untouched for N days\").",
    "    Opening the sidebar alone never acts on anything - it only holds the switch and the buttons.",
    "· Server-side hard guards: at most 12 packs at a time, never more than half of the enabled packs;",
    "    anything whose source changed within 3 days, anything another pack really imports, and the",
    "    never-touch list are left alone.",
    "· You can always press \"Show the plan first\" (changes nothing); running it needs a typed confirmation",
    "    phrase, and the result window offers one-click restore.",
    "· Left unticked it only scans when you press a button, and this pack has no prestartup script,",
    "    so it never slows down startup.",
    "",
    "[Sidebar and full panel]",
    "· The sidebar (X-WIDE icon on the left) carries the autopilot switch and its three buttons, the report",
    "    button, and two links: GitHub and Bilibili.",
    "· \"Open full panel\" opens the five-tab UI in a **new browser tab** (it no longer covers the canvas);",
    "    you can also open http://127.0.0.1:8188/xwide/plugin-manager/ui directly",
    "    (change the port to match your own ComfyUI).",
    "· Under the panel title you get the author line: X-WIDE, the version (click it for the GitHub repo),",
    "    GitHub repository, changelog, Bilibili page and issue tracker. The English / 中文 switch on the",
    "    right remembers your choice.",
    "· That page does not load the ComfyUI front end, so you only get this plugin's own UI - handy to keep on",
    "    a second monitor or to take screenshots.",
  ].join("\n");
  showRichModal(t("btn.help"), LANG === "zh" ? zh : en);
}

/* ------------------------------------------------------------------ 页 1：启动体检 */

function pageStartup(bodyNode, d) {
  if (!d) {
    bodyNode.appendChild(el("div", "xpm-note", t("common.empty")));
    return;
  }
  (d.errors || []).forEach((e) => bodyNode.appendChild(el("div", "xpm-errbox", e)));
  (d.notes || []).forEach((n) => bodyNode.appendChild(el("div", "xpm-warnbox", n)));

  const totalBox = el("div", "xpm-card");
  /* 合计卡：标签一行（20px）、数字另起一行（32px）——比原来挤在同一行里看得清 */
  const th = el("div", "xpm-card-body");
  th.appendChild(el("div", "xpm-biglabel", t("s.total")));
  const bigRow = el("div", "xpm-row");
  bigRow.appendChild(el("div", "xpm-big",
    (d.total === null || d.total === undefined ? "-" : fmtSecs(d.total) + " " + t("common.seconds"))));
  th.appendChild(bigRow);
  totalBox.appendChild(th);

  const tb = el("div", "xpm-card-body");
  const segRows = (d.segments || []).map((s) => ({
    name: LANG === "zh" ? s.label_zh : s.label_en,
    sec: s.seconds,
  }));
  tb.appendChild(table([
    { label: t("s.seg"), key: "name" },
    {
      label: t("common.seconds"),
      key: "sec",
      width: "140px",
      render: (r) => (r.sec === null || r.sec === undefined ? "-" : fmtSecs(r.sec) + " s"),
    },
  ], segRows));
  if (d.log) {
    tb.appendChild(kv([
      [t("s.logInfo"), (d.log.file || "") + (d.log.mtime ? "（" + d.log.mtime + "）" : "")],
      [t("s.window"), [
        d.log.process_start ? t("s.kProc") + " " + d.log.process_start : null,
        d.log.started ? t("s.kLog") + " " + d.log.started : null,
        d.log.server_at ? t("s.kServer") + " " + d.log.server_at : null,
        d.log.gui_ready ? t("s.kGui") + " " + d.log.gui_ready : null,
      ].filter(Boolean).join("  →  ")],
      [t("s.logTotals"), t("s.phase.pre") + " " + ((d.totals || {}).prestartup || 0) + " s + " +
        t("s.phase.imp") + " " + ((d.totals || {}).imports || 0) + " s"],
      [t("common.generated"), d.generated],
    ]));
  }
  totalBox.appendChild(tb);
  bodyNode.appendChild(totalBox);

  const rows = (d.by_pack || []).map((p) => ({
    name: p.name,
    seconds: p.seconds,
    phases: (p.phases || []).map((x) => (x === "prestartup" ? t("s.phase.pre") : t("s.phase.imp"))).join(" + "),
    failed: p.failed,
  }));
  bodyNode.appendChild(card(t("s.packTable"), table([
    { label: t("common.name"), key: "name" },
    { label: t("common.seconds"), key: "seconds", width: "120px", render: (r) => fmtSecs(r.seconds) + " s" },
    { label: t("s.phaseCol"), key: "phases", width: "170px" },
    { label: "", width: "130px", render: (r) => (r.failed ? badge("IMPORT FAILED", "bad") : "") },
  ], rows, { rowClass: (r) => (r.failed ? "xpm-tr-bad" : "") })));

  if ((d.failed || []).length) {
    const ul = el("ul", "xpm-list");
    d.failed.forEach((f) => ul.appendChild(el("li", "", f)));
    bodyNode.appendChild(card(t("s.failed"), ul));
  }
  if ((d.degrade || []).length) {
    const ul = el("ul", "xpm-list");
    d.degrade.forEach((f) => ul.appendChild(el("li", "xpm-code", f)));
    bodyNode.appendChild(card(t("s.degrade"), ul));
  }
}

/* ------------------------------------------------------------------ 页 2：插件分析 */

function packRisk(p) {
  /* 0 = 干净，1 = 有风险，2 = 尽量别动 */
  if (p.keep_never) return 2;
  if (p.refs_total > 0 || p.workflows_total > 0 || (p.unknown && p.unknown.length)) return 1;
  return 0;
}

function packRiskBadge(p) {
  const r = packRisk(p);
  if (r === 2) return badge(t("p.keep"), "bad");
  if (r === 1) return badge(t("p.risky"), "warn");
  return badge(t("p.safe"), "good");
}

/* --------------------------------------------------- 自动处理（第 2 页里的一段） */
/*
 * 规则全在服务端（autopilot.py）：只挑「没有任何工作流用过」或「很久没用」的包；
 * 真依赖、文档里声明依赖、基础设施（KEEP_NEVER）、源码 3 天内改过（可能正在开发）
 * 一律不动，单次还有上限。这里只负责四件事：
 *   改设置 / 看计划（dry_run，永远不改动任何东西）/ 按计划执行（要手打确认词）/ 一键恢复。
 */
function autopilotCard(opts) {
  const SIDE = !!(opts && opts.side);   /* 侧边栏里的小号版：短提示、而且不自动跑（避免“点开侧边栏就被禁用”） */
  const wrap = el("div", "xpm-card");
  wrap.appendChild(el("div", "xpm-card-title", xt("autoTitle")));
  if (SIDE) wrap.appendChild(el("div", "xpm-note", xt("autoWarnShort")));
  else wrap.appendChild(el("div", "xpm-warnbox", xt("autoWarn")));
  const body = el("div");
  wrap.appendChild(body);

  const st = { enabled: false, mode: "never_used", days: 90, last_run: null, managed: [] };

  function render() {
    clear(body);
    const on = el("input");
    on.type = "checkbox";
    on.checked = !!st.enabled;
    on.id = SIDE ? "xpm-auto-on-side" : "xpm-auto-on";
    on.addEventListener("change", async () => {
      if (on.checked) {
        /* 打开它 = 同意“主动禁用”：用自绘确认窗（原生 confirm 没法排版、也没法把硬保护标色） */
        const ok = await confirmModal(xt("autoEnableTitle"), [
          { kind: "warn", text: xt("autoEnableAsk") },
          { kind: "list", items: [xt("autoGuard1"), xt("autoGuard2"), xt("autoGuard3")] },
          { text: xt("autoEnableFoot") },
        ], t("common.confirm"), true);
        if (!ok) {
          on.checked = false;
          return;
        }
      }
      save({ enabled: on.checked });
    });
    const onLab = el("label", "xpm-note", st.enabled ? xt("autoOn") : xt("autoOff"));
    onLab.setAttribute("for", on.id);
    const row = el("div", "xpm-row");
    row.appendChild(on);
    row.appendChild(onLab);
    body.appendChild(row);

    const row2 = el("div", "xpm-row");
    row2.appendChild(el("span", "xpm-note", xt("autoMode") + "："));
    const sel = el("select", "xpm-select");
    [["never_used", xt("autoModeA")], ["never_used_or_stale", xt("autoModeB")]].forEach((o) => {
      const op = el("option", "", o[1]);
      op.value = o[0];
      op.selected = (st.mode === o[0]);
      sel.appendChild(op);
    });
    sel.addEventListener("change", () => save({ mode: sel.value }));
    row2.appendChild(sel);
    if (st.mode === "never_used_or_stale") {
      const days = el("input", "xpm-input");
      days.type = "number";
      days.min = "1";
      days.max = "3650";
      days.value = String(st.days || 90);
      days.style.minWidth = "90px";
      days.addEventListener("change", () => save({ days: parseInt(days.value, 10) || 90 }));
      row2.appendChild(el("span", "xpm-note", xt("autoDays") + "："));
      row2.appendChild(days);
    }
    body.appendChild(row2);

    const row3 = el("div", "xpm-row");
    const bPlan = regAutoBtn(btn(xt("autoPlan"), "primary xpm-auto-btn", () => showAutopilotPlan(false)));
    const bDo = regAutoBtn(btn(xt("autoDo"), "danger xpm-auto-btn", () => showAutopilotPlan(true)));
    const bRestore = regAutoBtn(btn(xt("autoRestore"), "ghost xpm-auto-btn", doAutopilotRestore));
    if (S.autoBusy) {                       /* 正在跑：三个按钮全部锁住，避免重复执行 */
      bPlan.disabled = true;
      bDo.disabled = true;
      bRestore.disabled = true;
    }
    row3.appendChild(bPlan);
    row3.appendChild(bDo);
    row3.appendChild(bRestore);
    body.appendChild(row3);
    if (S.autoBusy) {
      const lock = el("div", "xpm-busy");
      lock.appendChild(el("span", "xpm-spin", "◐"));
      lock.appendChild(el("span", "", xt("autoLocked")));
      body.appendChild(lock);
    }

    body.appendChild(kv([
      [xt("autoLast"), st.last_run || "-"],
      [xt("autoManaged", (st.managed || []).length), (st.managed || []).join("、") || "-"],
    ]));
  }

  /* 打开自动处理之后，进入本页就真的按服务端规则跑一遍（“主动禁用”），不是只给个计划。
   * 每进入一次页面只跑一次（S.autoVisit 由页签点击置位），跑完弹结果窗并刷新各页数字。 */
  async function maybeAutoRun() {
    if (SIDE) return;                       /* 侧边栏从不自动跑，只给开关和按钮 */
    if (!st.enabled || !S.autoVisit || S.autoBusy) return;
    S.autoVisit = false;
    autoBusyBegin(body, xt("autoPlanning"));  /* 卡片里也显示「进行中 + 已等待 N 秒」 */
    try {
      const j = await apiPost("/auto", { dry_run: false });
      const r = j.result || {};
      st.last_run = r.generated || st.last_run;
      st.managed = r.managed || st.managed;
      toast(r.failed ? "warn" : "success",
        r.done ? xt("autoApplied", r.done) : xt("autoAllDone"));
      showAutopilotResult(r);
      refreshAfterAutopilot();
    } catch (e) {
      toast("error", xt("autoErr", strOf(e)));
    } finally {
      autoBusyEnd();
      render();
    }
  }

  async function save(patch) {
    try {
      const j = await apiPost("/settings", patch);
      Object.assign(st, j.data || {});
      render();
      toast("success", xt("autoSaved"));
      if (patch.enabled === true) {           /* 刚打开：立刻按新设置跑一次 */
        S.autoVisit = true;
        maybeAutoRun();
      }
    } catch (e) {
      toast("error", xt("autoErr", strOf(e)));
    }
  }

  clear(body);
  body.appendChild(el("div", "xpm-note", t("common.loading")));
  apiGet("/settings").then((j) => {
    Object.assign(st, j.data || {});
    render();
    maybeAutoRun();
  }).catch((e) => {
    clear(body);
    body.appendChild(el("div", "xpm-errbox", xt("autoErr", strOf(e))));
  });
  return wrap;
}

/* 长任务的「进行中」提示：转圈 + 已等待秒数。自动处理要跑几十秒（扫工作流 + 扫依赖），
   之前点完按钮界面上什么都不显示、只有最后弹一个完成窗，看着像没反应，就容易被反复点
   —— 用户反馈「按计划执行时没有任何提示，好像会多次执行」。返回 stop()，任务结束时删掉这一行。 */
function startBusy(host, label) {
  const box = el("div", "xpm-busy");
  const sp = el("span", "xpm-spin", "◐");
  const txt = el("span", "", label + "…");
  const sec = el("span", "xpm-note", "");
  box.appendChild(sp);
  box.appendChild(txt);
  box.appendChild(sec);
  host.appendChild(box);
  const t0 = Date.now();
  const iv = setInterval(() => {
    const s = (Date.now() - t0) / 1000;
    sp.textContent = "◐◓◑◒".charAt(Math.floor(s * 4) % 4);
    sec.textContent = xt("autoPhase", s.toFixed(1));
  }, 140);
  return function stop() {
    clearInterval(iv);
    if (box.parentNode) box.remove();
  };
}

/* 搜索框防抖：表格动辄几百行，每敲一个键就整页重画会明显卡顿（用户反馈「在这里输入会很卡」）。
   延迟 220 ms 再画一次，连续输入期间不重画。 */
function debounce(fn, ms) {
  let timer = null;
  return function () {
    const args = arguments;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn.apply(null, args);
    }, ms || 220);
  };
}

/* 「自动处理」同一时刻只允许一个在跑：全局锁 + 所有入口按钮一起锁住。
   按钮在这里登记（不依赖 querySelectorAll —— 老前端或测试环境可能没有），
   侧边栏和完整面板各有一份卡片，两边都会锁上，所以不管从哪儿点的、点了多少次都不会重复执行。 */
let _autoStop = null;
const _autoBtns = [];

function regAutoBtn(b) {
  if (b) {
    _autoBtns.push(b);
    b.disabled = !!S.autoBusy;
  }
  return b;
}

function syncAutoButtons() {
  for (let i = _autoBtns.length - 1; i >= 0; i--) {
    const b = _autoBtns[i];
    if (!b || b.parentNode === null) { _autoBtns.splice(i, 1); continue; }   /* 卡片重画后旧按钮已经脱离文档 */
    b.disabled = !!S.autoBusy;
  }
  try {                                    /* DOM 里的一起锁（两份卡片同时存在时） */
    const list = document.querySelectorAll(".xpm-auto-btn");
    for (let i = 0; i < list.length; i++) list[i].disabled = !!S.autoBusy;
  } catch (e) { /* 没有 querySelectorAll 也不影响主流程 */ }
}

function autoBusyBegin(host, label) {
  S.autoBusy = true;
  if (_autoStop) { try { _autoStop(); } catch (e) { /* 上一个指示器已经没了 */ } _autoStop = null; }
  if (host) _autoStop = startBusy(host, label || xt("autoDoing"));
  syncAutoButtons();
}

function autoBusyEnd() {
  S.autoBusy = false;
  if (_autoStop) { try { _autoStop(); } catch (e) { /* 同上 */ } _autoStop = null; }
  syncAutoButtons();
}

function strOf(e) {
  return String(e && e.message ? e.message : e);
}

function apTable(rows) {
  return table([
    { label: xt("autoColName"), key: "name", width: "300px" },
    { label: xt("autoColCost"), width: "110px", render: (r) => fmtSecs(r.cost) + " s" },
    { label: xt("autoColNodes"), key: "nodes", width: "90px" },
    { label: xt("autoColWhy"), render: (r) => el("span", "xpm-note", r.reason || "") },
  ], rows || []);
}

function apDetails(title, rows) {
  const box = el("details", "xpm-details");
  box.appendChild(el("summary", "", title));
  const ul = el("ul", "xpm-list");
  (rows || []).forEach((r) => {
    ul.appendChild(el("li", "", (r.name || "") + "　" + fmtSecs(r.cost) + " s　" + (r.reason || "")));
  });
  box.appendChild(ul);
  return box;
}

async function showAutopilotPlan(execute) {
  if (S.autoBusy) {                         /* 上一次还在跑：先说清楚，不再发第二次请求 */
    toast("warn", xt("autoBusyWait"));
    return;
  }
  autoBusyBegin(null, null);              /* 算计划期间也上锁：连点两次不会发两次请求 */
  let stopBusy = null;
  const m = showModal(execute ? xt("autoDo") : xt("autoPlan"), (bodyNode) => {
    /* 第一步（算计划）本身就要跑十几秒到一分钟，先给「进行中 + 已等待 N 秒」 */
    stopBusy = startBusy(bodyNode, xt("autoPlanning"));
  });
  let d = null;
  try {
    const j = await apiPost("/auto", { dry_run: true });   /* 永远是 dry_run：这一步不改任何东西 */
    d = j.result || {};
  } catch (e) {
    if (stopBusy) { stopBusy(); stopBusy = null; }
    autoBusyEnd();
    clear(m.body);
    m.body.appendChild(el("div", "xpm-errbox", xt("autoErr", strOf(e))));
    return;
  }
  if (stopBusy) { stopBusy(); stopBusy = null; }
  autoBusyEnd();
  clear(m.body);
  m.body.appendChild(kv([
    [xt("autoMode"), (d.mode || "-") + "　" + fmtSecs((d.thresholds || {}).cost_min) + " s 起"],
    [t("common.generated"), d.generated || "-"],
  ]));
  m.body.appendChild(el("div", "xpm-warnbox",
    xt("autoWillDisable", (d.candidates || []).length, d.would_save || 0)));
  if (!(d.candidates || []).length) {
    m.body.appendChild(el("div", "xpm-note", xt("autoNone")));
  } else {
    m.body.appendChild(apTable(d.candidates));
  }
  if ((d.blocked || []).length) m.body.appendChild(apDetails(xt("autoBlocked", d.blocked.length), d.blocked));
  if ((d.skipped || []).length) m.body.appendChild(apDetails(xt("autoSkipped", d.skipped.length), d.skipped));
  if ((d.over_cap || []).length) m.body.appendChild(apDetails(xt("autoOver", d.over_cap.length), d.over_cap));
  (d.errors || []).forEach((e) => m.body.appendChild(el("div", "xpm-errbox", String(e))));

  if (!execute || !(d.candidates || []).length) return;
  m.body.appendChild(el("div", "xpm-note", t("risk.typeHere")));
  m.body.appendChild(el("div", "xpm-code", xt("confirmWord")));
  const inp = el("input", "xpm-input");
  inp.style.width = "100%";
  m.body.appendChild(inp);
  m.body.appendChild(el("div", "xpm-note", t("risk.restart")));
  const row = el("div", "xpm-row");
  row.appendChild(btn(t("common.cancel"), "ghost", () => m.close()));
  row.appendChild(btn(t("common.confirm"), "danger xpm-auto-btn", async () => {
    if (inp.value !== xt("confirmWord")) {
      toast("warn", t("risk.word") + "：" + xt("confirmWord"));
      return;
    }
    if (S.autoBusy) {
      toast("warn", xt("autoBusyWait"));
      return;
    }
    /* 就地显示进度：原来点了确定这个窗就关了，中间几十秒什么都看不到，只有最后弹结果
       —— 用户反馈「按计划执行时没有任何提示，好像会多次执行」。 */
    clear(m.body);
    m.body.appendChild(el("div", "xpm-warnbox",
      xt("autoWillDisable", (d.candidates || []).length, d.would_save || 0)));
    const stopDo = startBusy(m.body, xt("autoDoing"));
    autoBusyBegin(null, null);            /* 只上锁、不再插第二个指示器 */
    try {
      const j = await apiPost("/auto", { dry_run: false });
      const r = j.result || {};
      stopDo();
      autoBusyEnd();
      clear(m.body);
      m.body.appendChild(kv([
        [xt("autoResDone"), String(r.done || 0) + " / " + String(r.failed || 0)],
        [xt("autoResSave"), fmtSecs(r.would_save || 0) + " s"],
        [xt("autoManaged", (r.managed || []).length), (r.managed || []).join("、") || "-"],
      ]));
      if ((r.candidates || []).length) m.body.appendChild(apTable(r.candidates));
      (r.results || []).filter((x) => x && x.ok === false).forEach((x) =>
        m.body.appendChild(el("div", "xpm-errbox", (x.name || "") + "：" + (x.message || ""))));
      const row2 = el("div", "xpm-row");
      row2.appendChild(btn(xt("autoRestore"), "ghost", () => { m.close(); doAutopilotRestore(); }));
      row2.appendChild(btn(t("common.close"), "primary", () => m.close()));
      m.body.appendChild(row2);
      toast(r.failed ? "warn" : "success",
        xt("autoApplied", r.done || 0) + (r.failed ? "；" + xt("autoFailed", r.failed) : ""));
      refreshAfterAutopilot();
    } catch (e) {
      stopDo();
      autoBusyEnd();
      clear(m.body);
      m.body.appendChild(el("div", "xpm-errbox", xt("autoErr", strOf(e))));
    }
  }));
  m.body.appendChild(row);
}

/* 自动处理跑完的结果窗：这次禁用了什么、省了多少、失败项、以及一键恢复入口 */
function showAutopilotResult(r) {
  const rows = r.candidates || [];
  const m = showModal(xt("autoResultTitle"), (bodyNode) => {
    bodyNode.appendChild(kv([
      [xt("autoMode"), (r.mode || "-")],
      [t("common.generated"), r.generated || "-"],
      [xt("autoResDone"), String(r.done || 0) + " / " + String(r.failed || 0)],
      [xt("autoResSave"), fmtSecs(r.would_save || 0) + " s"],
      [xt("autoManaged", (r.managed || []).length), (r.managed || []).join("、") || "-"],
    ]));
    if (rows.length) bodyNode.appendChild(apTable(rows));
    (r.results || []).filter((x) => x && x.ok === false).forEach((x) =>
      bodyNode.appendChild(el("div", "xpm-errbox", (x.name || "") + "：" + (x.message || ""))));
    (r.errors || []).forEach((e) => bodyNode.appendChild(el("div", "xpm-errbox", String(e))));
    const row = el("div", "xpm-row");
    row.appendChild(btn(xt("autoRestore"), "ghost", () => { m.close(); doAutopilotRestore(); }));
    row.appendChild(btn(t("common.close"), "primary", () => m.close()));
    bodyNode.appendChild(row);
  });
}

async function doAutopilotRestore() {
  if (S.autoBusy) {                          /* 有任务在跑时别插队，免得两边同时改目录 */
    toast("warn", xt("autoBusyWait"));
    return;
  }
  if (!(await confirmModal(xt("autoRestore"), [{ text: xt("autoRestoreAsk") }], t("common.confirm"), false))) return;
  autoBusyBegin(null, null);
  try {
    const j = await apiPost("/auto/restore", {});
    const d = j.result || {};
    toast(d.done ? "success" : "warn", d.done ? xt("autoRestored", d.done) : xt("autoNothing"));
    refreshAfterAutopilot();
  } catch (e) {
    const msg = strOf(e);
    if (/400/.test(msg)) toast("warn", xt("autoNothing"));
    else toast("error", xt("autoErr", msg));
  } finally {
    autoBusyEnd();
  }
}

function refreshAfterAutopilot() {
  S.loaded.packs = false;
  S.loaded.log = false;
  S.loaded.startup = false;
  S.loaded.workflows = false;
  S.loaded.models = false;
  if (S.tab === "packs") loadTab("packs", true);
  else if (S.tab === "log") loadTab("log", true);
  else renderActive();
}

function pagePacks(bodyNode, d) {
  if (!d) {
    bodyNode.appendChild(el("div", "xpm-note", t("common.empty")));
    return;
  }
  (d.errors || []).forEach((e) => bodyNode.appendChild(el("div", "xpm-errbox", e)));

  const man = d.manifest || {};
  const dc = d.deps_cache || {};
  const depsTxt = t("p.depsLine", dc.reused || 0, dc.scanned || 0,
    (dc.seconds === null || dc.seconds === undefined ? "-" : fmtSecs(dc.seconds))) +
    (dc.write_error ? "　⚠️ " + t("p.depsWriteErr", dc.write_error) : "");
  const info = el("div", "xpm-row");
  info.appendChild(badge(t("p.stats", (d.counts || {}).packs, (d.counts || {}).enabled, (d.counts || {}).disabled), "info"));
  info.appendChild(badge(t("s.phase.pre") + " " + ((d.totals || {}).prestartup || 0) + " s + " +
    t("s.phase.imp") + " " + ((d.totals || {}).imports || 0) + " s", "plain"));
  info.appendChild(badge(t("common.generated") + " " + (d.generated || "-"), "plain"));
  if (man.fresh === false) info.appendChild(badge(t("p.snapshotStale"), "warn"));
  if (dc.write_error) info.appendChild(badge("⚠️ " + t("p.depsIndex"), "warn"));
  bodyNode.appendChild(card(t("title"), [
    info,
    kv([
      [t("p.snapshot"), man.source],
      [t("common.pluginDirs"), (d.counts || {}).packs + "　" + (d.workflow_dir || "")],
      [t("p.depsIndex"), depsTxt],
      [t("common.notes"), t("p.candHint", (d.thresholds || {}).cost_min) + "；" + t("p.riskyHint")],
    ]),
  ]));

  /* 自动处理（服务端规则 + 先看计划 + 手打确认词才执行） */
  bodyNode.appendChild(autopilotCard());

  /* 工具栏 */
  const bar = el("div", "xpm-toolbar");
  const search = el("input", "xpm-input");
  search.placeholder = t("common.search");
  search.value = S.filter.packs_q || "";
  const packsRedraw = debounce(() => renderActive(), 200);   /* 同样防抖：195 行的表不再每个按键重画 */
  search.addEventListener("input", () => {
    S.filter.packs_q = search.value;
    packsRedraw();
  });
  bar.appendChild(search);

  const seg = el("div", "xpm-seg");
  const FILTERS = [
    ["cand", t("p.filter.cand")],
    ["risky", t("p.filter.risky")],
    ["riskyDisabled", t("p.filter.riskyDisabled")],
    ["enabled", t("p.filter.enabled")],
    ["disabled", t("p.filter.disabled")],
    ["all", t("p.filter.all")],
  ];
  FILTERS.forEach((f) => {
    const b = el("button", S.filter.packs === f[0] ? "on" : "", f[1]);
    b.type = "button";
    b.addEventListener("click", () => {
      S.filter.packs = f[0];
      renderActive();
    });
    seg.appendChild(b);
  });
  bar.appendChild(seg);
  bodyNode.appendChild(card(t("tab.packs"), bar));

  /* 过滤与排序 */
  const all = d.packs || [];
  const cands = new Set(d.candidates || []);
  const riskyDis = new Set(d.risky_disabled || []);
  const q = (S.filter.packs_q || "").toLowerCase();
  const rows = all.filter((p) => {
    if (q && p.name.toLowerCase().indexOf(q) < 0) return false;
    if (S.filter.packs === "cand") return cands.has(p.name);
    if (S.filter.packs === "risky") return p.enabled && packRisk(p) === 1;
    if (S.filter.packs === "riskyDisabled") return riskyDis.has(p.name);
    if (S.filter.packs === "enabled") return p.enabled;
    if (S.filter.packs === "disabled") return !p.enabled;
    return true;
  });
  if (S.sort.packs === "name") {
    rows.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  } else {
    rows.sort((a, b) => (b.cost - a.cost) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  }

  /* 批量条 */
  const selBar = el("div", "xpm-row");
  const selCount = el("span", "xpm-note", t("p.sel") + " 0");
  selBar.appendChild(selCount);
  selBar.appendChild(btn(t("common.byName") + " / " + t("common.byCost"), "ghost", () => {
    S.sort.packs = S.sort.packs === "name" ? "cost" : "name";
    renderActive();
  }));
  selBar.appendChild(btn(t("p.selAll"), "ghost", () => {
    rows.forEach((r) => S.sel.add(r.name));
    renderActive();
  }));
  selBar.appendChild(btn(t("p.selNone"), "ghost", () => {
    S.sel.clear();
    renderActive();
  }));
  selBar.appendChild(btn(t("p.batchDisable"), "danger", () => {
    const names = rows.filter((r) => S.sel.has(r.name) && r.enabled).map((r) => r.name);
    if (!names.length) {
      toast("warn", t("common.empty"));
      return;
    }
    batchAction("disable", names, d);
  }));
  selBar.appendChild(btn(t("p.batchEnable"), "", () => {
    const names = rows.filter((r) => S.sel.has(r.name) && !r.enabled).map((r) => r.name);
    if (!names.length) {
      toast("warn", t("common.empty"));
      return;
    }
    batchAction("enable", names, d);
  }));
  bodyNode.appendChild(card(t("p.sel"), selBar));

  /* 主表 */
  const cols = [
    {
      label: "",
      width: "36px",
      render: (r) => {
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = S.sel.has(r.name);
        cb.addEventListener("click", (e) => e.stopPropagation());
        cb.addEventListener("change", () => {
          if (cb.checked) S.sel.add(r.name);
          else S.sel.delete(r.name);
          selCount.textContent = t("p.sel") + " " + S.sel.size;
        });
        return cb;
      },
    },
    {
      label: t("p.col.name"),
      key: "name",
      render: (r) => {
        const wrap = el("div", "xpm-row");
        wrap.appendChild(el("span", "", r.name));
        wrap.appendChild(badge(r.enabled ? t("common.enabled") : t("common.disabled"), r.enabled ? "good" : "plain"));
        if (r.keep_never) wrap.appendChild(badge(t("p.keepNever"), "bad"));
        return wrap;
      },
    },
    {
      label: t("p.col.desc"),
      key: "desc",
      width: "300px",
      /* 简介最多两行、超出用省略号，鼠标悬停看全文 —— 否则一句英文简介会把行撑成十几行高 */
      render: (r) => {
        if (!r.desc) return el("span", "");
        const s = el("span", "xpm-desc", r.desc);
        try { s.title = r.desc; } catch (e) { /* 忽略 */ }
        return s;
      },
    },
    { label: t("p.col.cost"), width: "120px", render: (r) => (r.cost > 0 ? fmtSecs(r.cost) + " s" : "-") },
    { label: t("p.col.nodes"), width: "90px", render: (r) => (r.nodes || 0) },
    {
      label: t("p.col.wf"),
      width: "170px",
      render: (r) => (r.workflows_total ? t("p.wfCount", r.workflows_total) : t("p.noneWf")),
    },
    {
      label: t("p.col.risk"),
      width: "170px",
      render: (r) => {
        const wrap = el("div", "xpm-row");
        wrap.appendChild(packRiskBadge(r));
        if (r.refs_total) wrap.appendChild(badge("↩ " + r.refs_total, "warn"));
        return wrap;
      },
    },
    { label: t("p.col.src"), width: "130px", render: (r) => r.detail || "" },
    {
      label: "",
      width: "230px",
      render: (r) => {
        const wrap = el("div", "xpm-row");
        wrap.appendChild(btn(S.expanded.has(r.name) ? t("btn.less") : t("btn.more"), "ghost", () => {
          if (S.expanded.has(r.name)) S.expanded.delete(r.name);
          else S.expanded.add(r.name);
          renderActive();
        }));
        if (r.enabled) wrap.appendChild(btn(t("btn.disable"), "danger", () => oneAction("disable", r)));
        else wrap.appendChild(btn(t("btn.enable"), "", () => oneAction("enable", r)));
        return wrap;
      },
    },
  ];
  bodyNode.appendChild(card(t("tab.packs"), table(cols, rows, {
    rowClass: (r) => (packRisk(r) === 2 ? "xpm-tr-bad" : (packRisk(r) === 1 && !r.enabled ? "xpm-tr-warn" : "")),
  })));

  /* 展开的详情 */
  rows.filter((r) => S.expanded.has(r.name)).forEach((r) => {
    const box = el("div", "xpm-details");
    const head = el("div", "xpm-row");
    head.appendChild(el("strong", "", r.name));
    head.appendChild(packRiskBadge(r));
    box.appendChild(head);
    if (r.note) box.appendChild(el("div", "xpm-note", t("p.note") + "：" + r.note));
    box.appendChild(kv([
      [t("common.dir"), r.dir || ""],
      [t("p.costDetail"), r.detail || "-"],
      [t("p.broad"), r.broad ? (r.broad.packs + " " + t("p.packsTotal") + r.broad.refs + " " + t("p.refsTotal")) : null],
    ]));

    if ((r.refs || []).length) {
      box.appendChild(el("div", "xpm-note", t("p.refsOn") + "（" + r.refs_total + "）"));
      const ul = el("ul", "xpm-list");
      r.refs.forEach((e) => {
        const li = el("li");
        li.appendChild(el("span", "", "[" + e.from + "] "));
        li.appendChild(el("span", "xpm-code", e.file + ":" + e.line));
        if (e.text) li.appendChild(el("div", "xpm-note", e.text));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    } else {
      box.appendChild(el("div", "xpm-note", t("p.noRefs")));
    }
    if ((r.refs_disabled || []).length) {
      box.appendChild(el("div", "xpm-note", t("p.refsOff") + "（" + r.refs_disabled_total + "）"));
      const ul = el("ul", "xpm-list");
      r.refs_disabled.forEach((e) => {
        ul.appendChild(el("li", "xpm-code", "[" + e.from + "] " + e.file + ":" + e.line));
      });
      box.appendChild(ul);
    }
    if ((r.workflows || []).length) {
      box.appendChild(el("div", "xpm-note", t("p.wfUsed") + "（" + r.workflows_total + "）"));
      const ul = el("ul", "xpm-list");
      r.workflows.forEach((w) => ul.appendChild(el("li", "", w)));
      box.appendChild(ul);
    }
    if ((r.unknown || []).length) {
      box.appendChild(el("div", "xpm-note", t("p.unknownUsed")));
      const ul = el("ul", "xpm-list");
      r.unknown.forEach((u) => ul.appendChild(el("li", "xpm-code", u.type + "  " + u.file + ":" + u.line)));
      box.appendChild(ul);
    }
    bodyNode.appendChild(card(r.name, box));
  });

  if ((d.orphans || []).length) {
    const ul = el("ul", "xpm-list");
    d.orphans.slice(0, 60).forEach((o) => {
      ul.appendChild(el("li", "", o.type + (o.workflows && o.workflows.length ? "  ←  " + o.workflows.join(" / ") : "")));
    });
    bodyNode.appendChild(card(t("p.orphanTitle"), ul));
  }

  if ((d.folded || []).length) {
    const ul = el("ul", "xpm-list");
    d.folded.slice(0, 40).forEach((f) => {
      ul.appendChild(el("li", "", f.name + " —— " + f.packs + " " + t("p.packsTotal") + f.refs + " " + t("p.refsTotal")));
    });
    bodyNode.appendChild(card(t("p.foldedTitle"), ul));
  }
}

/* ------------------------------------------------------------------ 页 3：工作流分析 */

function pageWorkflows(bodyNode, d) {
  if (!d) {
    bodyNode.appendChild(el("div", "xpm-note", t("common.empty")));
    return;
  }
  (d.errors || []).forEach((e) => bodyNode.appendChild(el("div", "xpm-errbox", e)));
  const b = d.buckets || {};
  const info = el("div", "xpm-row");
  /* 分桶徽标点一下＝只看这一类（再点取消）；"d90" 是后端用的键，界面上写「31-90 天」 */
  const bucketKeyOf = (days) => (days <= 7 ? "d7" : (days <= 30 ? "d30" : (days <= 90 ? "d90" : "older")));
  const bucketBadge = (label, n, kind, key) => {
    const node = badge(label + " " + n, kind);
    node.classList.add("xpm-bucket");
    if (S.filter.wfBucket === key) node.classList.add("on");
    node.title = S.filter.wfBucket === key ? t("w.bucketClear") : t("w.bucketHint");
    node.addEventListener("click", () => {
      S.filter.wfBucket = (S.filter.wfBucket === key ? "" : key);
      if (S.filter.wfBucket) S.filter.wfOnly = true;      /* 点了分桶默认只看这一类 */
      renderActive();
    });
    return node;
  };
  info.appendChild(bucketBadge(t("w.b7"), b.d7 || 0, "good", "d7"));
  info.appendChild(bucketBadge(t("w.b30"), b.d30 || 0, "info", "d30"));
  info.appendChild(bucketBadge(t("w.b90"), b.d90 || 0, "warn", "d90"));
  info.appendChild(bucketBadge(t("w.bOld"), b.older || 0, "bad", "older"));
  info.appendChild(badge(t("common.total") + " " + (d.count || 0), "plain"));
  const man = d.manifest || {};
  if (man.fresh === false) info.appendChild(badge(t("p.snapshotStale"), "warn"));
  const onlyRowW = el("div", "xpm-row");
  const cbOnly = el("input");
  cbOnly.type = "checkbox";
  cbOnly.checked = !!S.filter.wfOnly;
  cbOnly.addEventListener("change", () => {
    S.filter.wfOnly = cbOnly.checked;
    renderActive();
  });
  onlyRowW.appendChild(cbOnly);
  onlyRowW.appendChild(el("span", "xpm-note", t("w.onlyBucket")));
  if (S.filter.wfBucket) {
    onlyRowW.appendChild(badge(t("w.bucketOn", t("w.b" + (S.filter.wfBucket === "d7" ? "7" : (S.filter.wfBucket === "d30" ? "30" : (S.filter.wfBucket === "d90" ? "90" : "Old"))))), "info"));
  }
  bodyNode.appendChild(card(t("w.bucket"), [
    info,
    el("div", "xpm-note", t("w.bucketNote")),
    onlyRowW,
    el("div", "xpm-note", t("w.dir") + "：" + (d.dir || "") + "　" + t("w.notes")),
  ]));

  const bar = el("div", "xpm-row");
  const sel = el("select", "xpm-select");
  const optAll = el("option", "", t("p.filter.all"));
  optAll.value = "";
  sel.appendChild(optAll);
  (d.pack_wfs || []).forEach((p) => {
    const o = el("option", "", p.name + "（" + p.count + "）" + (p.enabled ? "" : " [" + t("common.disabled") + "]"));
    o.value = p.name;
    sel.appendChild(o);
  });
  sel.value = S.filter.wfPack || "";
  sel.addEventListener("change", () => {
    S.filter.wfPack = sel.value;
    renderActive();
  });
  bar.appendChild(el("span", "xpm-note", t("w.filter.pack")));
  bar.appendChild(sel);

  const cb = el("input");
  cb.type = "checkbox";
  cb.checked = !!S.filter.wfMissing;
  cb.addEventListener("change", () => {
    S.filter.wfMissing = cb.checked;
    renderActive();
  });
  bar.appendChild(cb);
  bar.appendChild(el("span", "xpm-note", t("w.filter.missing")));

  const q = el("input", "xpm-input");
  q.placeholder = t("common.search");
  q.value = S.filter.wf_q || "";
  const wfRedraw = debounce(() => renderActive(), 200);   /* 防抖：工作流表也不再每个按键重画 */
  q.addEventListener("input", () => {
    S.filter.wf_q = q.value;
    wfRedraw();
  });
  bar.appendChild(q);
  bodyNode.appendChild(card(t("tab.workflows"), bar));

  let rows = d.items || [];
  if (S.filter.wfPack) rows = rows.filter((r) => (r.packs || []).indexOf(S.filter.wfPack) >= 0);
  if (S.filter.wfMissing) rows = rows.filter((r) => (r.missing_total || 0) > 0);
  if (S.filter.wfBucket && S.filter.wfOnly) {
    rows = rows.filter((r) => bucketKeyOf(r.age_days) === S.filter.wfBucket);
  }
  const qq = (S.filter.wf_q || "").toLowerCase();
  if (qq) rows = rows.filter((r) => r.name.toLowerCase().indexOf(qq) >= 0);

  bodyNode.appendChild(card(t("tab.workflows"), table([
    { label: t("w.col.name"), key: "name", render: (r) => el("span", "xpm-clickable", r.name) },
    { label: t("w.col.mtime"), width: "170px", render: (r) => r.mtime + "（" + t("w.days", r.age_days) + "）" },
    { label: t("w.col.atime"), width: "160px", render: (r) => r.atime },
    { label: t("w.col.size"), width: "90px", render: (r) => r.size_h },
    {
      label: t("w.col.packs"),
      render: (r) => {
        const wrap = el("div");
        if (!r.packs_total) {
          wrap.appendChild(el("span", "xpm-note", t("w.none")));
          return wrap;
        }
        const key = "wf:" + r.name;
        const open = S.expanded.has(key);
        const all = r.packs || [];
        const descOf = d.pack_desc || {};
        const shown = open ? all : all.slice(0, 4);
        const line = el("div", "xpm-row");
        shown.forEach((n) => {
          const chip = el("span", "xpm-chip", n);
          if (descOf[n]) chip.title = descOf[n];
          line.appendChild(chip);
        });
        if (!open && all.length > shown.length) {
          line.appendChild(btn("+" + (all.length - shown.length), "ghost", () => {
            S.expanded.add(key);
            renderActive();
          }));
        } else if (open && all.length > 4) {
          line.appendChild(btn(t("common.less"), "ghost", () => {
            S.expanded.delete(key);
            renderActive();
          }));
        }
        wrap.appendChild(line);
        if ((r.packs_disabled || []).length) {
          wrap.appendChild(el("div", "xpm-note", t("w.packsDisabled", r.packs_disabled.join("、"))));
        }
        return wrap;
      },
    },
    {
      label: t("w.col.missing"),
      width: "200px",
      render: (r) => {
        const wrap = el("div");
        if (r.missing_total) {
          const b = badge(t("common.itemsN", r.missing_total), "warn");
          b.title = (r.missing || []).join("、");
          wrap.appendChild(b);
        }
        if (r.missing_js_total) {
          const b2 = badge(t("w.jsNode", r.missing_js_total), "info");
          const files = r.missing_js_files || {};
          b2.title = (r.missing_js || []).map((n) => n + (files[n] ? " ← " + files[n].join(", ") : "")).join("；");
          wrap.appendChild(b2);
        }
        if (!r.missing_total && !r.missing_js_total) wrap.appendChild(badge("-", "plain"));
        return wrap;
      },
    },
    { label: "", width: "110px", render: (r) => btn(t("btn.folder"), "ghost", () => openPath(r.path)) },
  ], rows, { rowClass: (r) => ((r.missing_total || 0) > 0 ? "xpm-tr-warn" : "") })));

  const pk = d.pack_wfs || [];
  if (pk.length) {
    bodyNode.appendChild(card(t("w.packTitle"), table([
      {
        label: t("p.col.name"),
        key: "name",
        width: "280px",
        render: (r) => {
          const wrap = el("div", "xpm-row");
          wrap.appendChild(el("span", "", r.name));
          if (!r.enabled) wrap.appendChild(badge(t("common.disabled"), "plain"));
          return wrap;
        },
      },
      { label: t("common.count"), key: "count", width: "80px" },
      {
        label: t("p.col.desc"),
        width: "300px",
        render: (r) => {
          if (!r.desc) return el("span", "");
          const s = el("span", "xpm-desc", r.desc);
          try { s.title = r.desc; } catch (e) { /* 忽略 */ }
          return s;
        },
      },
      { label: t("p.wfUsed"), render: (r) => (r.workflows || []).join("、") },
    ], pk)));
  }
}

/* ------------------------------------------------------------------ 页 4：模型分析 */

function tierLabel(k) {
  const key = "m." + k;
  const v = t(key);
  return v === key ? k : v;
}

function tierBadge(tier, label) {
  const kind = tier === "used" ? "good"
    : (tier === "auto_path" || tier === "auto_name" ? "info"
      : (tier === "auto_dir" ? "plain" : (tier === "unknown" ? "warn" : "bad")));
  return badge(label || tier, kind);
}

function pageModels(bodyNode, d) {
  if (!d) {
    bodyNode.appendChild(el("div", "xpm-note", t("common.empty")));
    return;
  }
  if (d.ok === false) {
    bodyNode.appendChild(el("div", "xpm-errbox", (d.error || "") + "　" + (d.hint || "")));
    return;
  }
  (d.errors || []).forEach((e) => bodyNode.appendChild(el("div", "xpm-errbox", e)));

  const tr = d.tiers || {};
  const unref = d.unref || {};
  const line1 = el("div", "xpm-row");
  line1.appendChild(el("span", "xpm-big", d.bytes_total_h || fmtBytes(d.bytes_total)));
  line1.appendChild(el("span", "xpm-note", t("m.total") + "　" + (d.weights || 0) + " " + t("m.weights") +
    "　/　" + (d.files_total || 0) + " " + t("m.files")));
  const line2 = el("div", "xpm-row");
  line2.appendChild(el("span", "xpm-big", unref.bytes_h || fmtBytes(unref.bytes)));
  line2.appendChild(el("span", "xpm-note", t("m.unref") + "　" + (unref.count || 0) + " " + t("m.weights")));

  const order = ["auto_path", "auto_name", "auto_dir", "unknown", "nobody"];
  const colors = {
    used: "#2f7d4f", auto_path: "#2a5bd7", auto_name: "#3a7fbf",
    auto_dir: "#6b6f7a", unknown: "#a3801f", nobody: "#8c2f2f",
  };
  const bar = el("div", "xpm-bar");
  const totalBytes = d.bytes_total || 1;
  ["used"].concat(order).forEach((k) => {
    const v = tr[k];
    if (!v || !v.bytes) return;
    const s = el("span");
    s.style.width = Math.max(0.4, (v.bytes / totalBytes) * 100) + "%";
    s.style.background = colors[k] || "#444";
    s.title = tierLabel(k) + " " + (v.bytes_h || fmtBytes(v.bytes));
    bar.appendChild(s);
  });

  /* 图例：色条下面那排色块现在也能当筛选用（用户要求「这块也起过滤作用」，图4）。
     点一下＝只看这一档，再点一下＝取消；下面「只看某一档」那排按钮是同一件事，
     两边共用 S.filter.models_tier，所以高亮永远同步。 */
  const tierUI = [];
  function paintTier() {
    tierUI.forEach((it) => {
      try { it.el.className = (it.base || "") + (it.key === S.filter.models_tier ? " on" : ""); }
      catch (e) { /* 忽略 */ }
    });
  }
  function setTier(k) {
    S.filter.models_tier = (S.filter.models_tier === k) ? "" : k;
    paintTier();
    drawTable();
  }
  const tierRow = el("div", "xpm-row xpm-legend");
  ["used"].concat(order).forEach((k) => {
    const v = tr[k];
    if (!v) return;
    const label = tierLabel(k) + " " + v.count + " / " + (v.bytes_h || fmtBytes(v.bytes));
    const b = el("button", "xpm-tierbtn" + (S.filter.models_tier === k ? " on" : ""));
    b.type = "button";
    b.title = label + "　" + xt("mLegendClick");
    b.appendChild(tierBadge(k, label));
    b.addEventListener("click", () => setTier(k));
    tierUI.push({ el: b, key: k, base: "xpm-tierbtn" });
    tierRow.appendChild(b);
  });

  bodyNode.appendChild(card(t("tab.models"), [
    line1,
    line2,
    bar,
    tierRow,
    el("div", "xpm-note", t("m.tierHint") + "　" + xt("mLegendClick")),
    (() => {
      /* 提示条限宽靠左：原来一行铺满整页，眼睛要横着扫很远（用户反馈） */
      const w = el("div", "xpm-warnbox xpm-warnbox-inline");
      w.appendChild(el("span", "", "ℹ️"));
      w.appendChild(el("span", "", t("m.neverDelete")));
      return w;
    })(),
    kv([
      [t("m.dir"), d.models_dir],
      [t("w.dir"), (d.workflow_dir || "") + t("common.inParen", d.workflows_scanned || 0)],
      [t("common.cached"), d.cached ? t("m.yes") : t("m.no")],
      [t("common.generated"), d.generated + "　" + t("m.sig",
        (d.seconds === null || d.seconds === undefined) ? "-" : d.seconds,
        d.cached ? "（" + t("common.cached") + "）" : "")],
    ]),
  ]));

  const lh = d.load_hook || {};
  bodyNode.appendChild(card(t("l.hooks"), [
    el("div", "xpm-note", lh.installed
      ? t("m.loadHookOn", lh.since || "-", lh.records || 0)
      : t("m.loadHookOff", lh.reason || "-")),
  ]));

  if ((d.autoload_dirs || []).length) {
    const rows = d.autoload_dirs.map((x) => ({
      dir: x.dir,
      count: x.count,
      bytes_h: x.bytes_h,
      unref: x.unref_count,
      unref_h: x.unref_bytes_h,
    }));
    const autoBox = el("details", "xpm-details");
    autoBox.appendChild(el("summary", "", t("m.autoload") + "（" + rows.length + "）"));
    autoBox.appendChild(table([
      { label: t("m.dirCol"), key: "dir" },
      { label: t("common.count"), key: "count", width: "90px" },
      { label: t("common.size"), key: "bytes_h", width: "110px" },
      { label: t("m.unrefIn"), key: "unref", width: "150px", render: (r) => r.unref + " / " + r.unref_h },
    ], rows));
    bodyNode.appendChild(autoBox);
  }

  const bar2 = el("div", "xpm-row");
  const q = el("input", "xpm-input");
  q.placeholder = t("common.search");
  q.value = S.filter.models_q || "";
  bar2.appendChild(q);

  /* 「按类型分组」勾选框（用户要求：所有类型做个分组）。默认开着，取消勾选回到平铺长表。 */
  const gcb = el("input");
  gcb.type = "checkbox";
  gcb.id = "xpm-models-group";
  gcb.checked = S.filter.models_group !== false;
  gcb.addEventListener("change", () => {
    S.filter.models_group = gcb.checked;
    drawTable();
  });
  bar2.appendChild(gcb);
  const glab = el("label", "xpm-note", t("m.group"));
  glab.setAttribute("for", "xpm-models-group");
  bar2.appendChild(glab);

  const seg = el("div", "xpm-seg");
  const tierFilters = [["", t("common.all")], ["unref", t("m.unref")]].concat(order.map((k) => [k, tierLabel(k)]));
  tierFilters.forEach((f) => {
    const b = el("button", S.filter.models_tier === f[0] ? "on" : "", f[1]);
    b.type = "button";
    /* 与上面的色块图例共用同一个状态：只切换高亮 + 重画表格，不动整页 */
    b.addEventListener("click", () => setTier(f[0]));
    tierUI.push({ el: b, key: f[0], base: "" });
    seg.appendChild(b);
  });
  bar2.appendChild(seg);
  bodyNode.appendChild(card(t("m.filter.tier"), [bar2, el("div", "xpm-note", t("m.groupHint"))]));

  /* 列定义：类型列只在「不分组」时才需要（分组时类型写在分组标题上） */
  const typeCol = { label: t("m.col.type"), key: "top", width: "120px" };
  const cols = [
    { label: t("m.col.model"), key: "rel", render: (r) => el("span", "xpm-code", r.rel) },
    { label: t("m.col.size"), key: "size_h", width: "100px" },
    { label: t("m.col.mtime"), key: "mtime", width: "150px" },
    { label: t("m.col.atime"), key: "atime", width: "150px" },
    {
      label: t("m.col.refs"),
      width: "140px",
      render: (r) => (r.ref_count ? badge(t("m.wfCount", r.ref_count), "good") : badge("-", "plain")),
    },
    { label: t("m.col.tier"), width: "200px", render: (r) => tierBadge(r.tier, r.tier_label || tierLabel(r.tier)) },
    {
      label: t("m.col.loads"),
      width: "150px",
      render: (r) => {
        const l = r.loads || {};
        if (!l.count) return el("span", "xpm-note", t("m.loadsNone"));
        return badge(t("m.times", l.count) + (l.last ? " / " + l.last : ""), "info");
      },
    },
    {
      label: "",
      width: "230px",
      render: (r) => {
        const wrap = el("div", "xpm-row");
        if ((r.refs || []).length || (r.evidence || []).length) {
          wrap.appendChild(btn(t("btn.evidence"), "ghost", () => showModelEvidence(r)));
        }
        wrap.appendChild(btn(t("btn.folder"), "ghost", () => openPath(d.models_dir + "\\" + r.rel)));
        return wrap;
      },
    },
  ];
  const rowClass = (r) => (r.tier === "nobody" && !r.ref_count ? "xpm-tr-warn" : "");

  /* 表格单独放进 host：搜索、切档、分组开关只重画这一块，不重画整页
     —— 原来是每个按键都 renderActive()，整页几百行重画，输入明显卡顿（用户反馈）。 */
  const host = el("div");
  bodyNode.appendChild(card(t("tab.models"), [host]));

  function drawTable() {
    clear(host);
    let items = d.items || [];
    const qq = (S.filter.models_q || "").toLowerCase();
    if (qq) items = items.filter((x) => x.rel.toLowerCase().indexOf(qq) >= 0);
    if (S.filter.models_tier === "unref") items = items.filter((x) => !x.ref_count);
    else if (S.filter.models_tier) items = items.filter((x) => x.tier === S.filter.models_tier);
    if (S.sort.models === "name") {
      items = items.slice().sort((a, b) => a.rel.toLowerCase().localeCompare(b.rel.toLowerCase()));
    } else {
      items = items.slice().sort((a, b) => b.size - a.size);
    }
    const shown = items.slice(0, 500);
    const tail = t("s.showing", shown.length, items.length, (d.items || []).length);
    const grouped = S.filter.models_group !== false;

    if (!grouped) {
      host.appendChild(table(cols.concat([typeCol]), shown, { rowClass }));
      host.appendChild(el("div", "xpm-note", t("m.groupFlat") + "　" + tail));
      return;
    }

    /* 按类型分组：一组一个可折叠块，标题后面跟「N 个 · 合计体积」，组内按当前排序 */
    const groups = {};
    shown.forEach((r) => {
      const k = r.top || "-";
      if (!groups[k]) groups[k] = [];
      groups[k].push(r);
    });
    const keys = Object.keys(groups).sort((a, b) => {
      const ba = groups[a].reduce((s, x) => s + (x.size || 0), 0);
      const bb = groups[b].reduce((s, x) => s + (x.size || 0), 0);
      return bb - ba;
    });
    const barPart = (k, g) => {
      const bytes = g.reduce((s, x) => s + (x.size || 0), 0);
      const box = el("details", "xpm-group");
      box.open = !S.modelsFolded.has(k);       /* 默认全部展开，折叠状态记在 S.modelsFolded */
      box.addEventListener("toggle", () => {
        if (box.open) S.modelsFolded.delete(k);
        else S.modelsFolded.add(k);
      });
      const sum = el("summary");
      sum.appendChild(el("span", "xpm-group-name", k));
      sum.appendChild(badge(t("m.groupSum", g.length, fmtBytes(bytes)), "plain"));
      box.appendChild(sum);
      box.appendChild(table(cols, g, { rowClass }));
      return box;
    };
    keys.forEach((k) => host.appendChild(barPart(k, groups[k])));
    host.appendChild(el("div", "xpm-note", t("m.groupOn", keys.length) + "　" + tail));
  }

  drawTable();
  /* 输入防抖：连续打字时只在停下来 200 ms 后重画一次 */
  const redrawSoon = debounce(drawTable, 200);
  q.addEventListener("input", () => {
    S.filter.models_q = q.value;
    redrawSoon();
  });
}

function showModelEvidence(r) {
  showModal(r.rel, (bodyNode) => {
    bodyNode.appendChild(kv([
      [t("common.size"), r.size_h],
      [t("m.col.mtime"), r.mtime],
      [t("m.col.atime"), r.atime],
      [t("m.col.tier"), (r.tier_label || r.tier) + "（" + r.tier + "）"],
    ]));
    if ((r.refs || []).length) {
      bodyNode.appendChild(el("div", "xpm-note", t("m.refsList") + "（" + r.ref_count + "）"));
      const ul = el("ul", "xpm-list");
      r.refs.forEach((w) => ul.appendChild(el("li", "", w)));
      bodyNode.appendChild(ul);
    }
    if ((r.evidence || []).length) {
      bodyNode.appendChild(el("div", "xpm-note", t("m.evidence")));
      const ul = el("ul", "xpm-list");
      r.evidence.forEach((e) => {
        const li = el("li");
        const where = typeof e === "string" ? e : ((e.file || "") + (e.line ? ":" + e.line : ""));
        const why = typeof e === "string" ? "" : (e.text || e.kind || "");
        li.appendChild(el("span", "xpm-code", where));
        if (why) li.appendChild(el("div", "xpm-note", String(why).slice(0, 300)));
        ul.appendChild(li);
      });
      bodyNode.appendChild(ul);
    }
  });
}

/* ------------------------------------------------------------------ 页 5：动作记录 */

function pageLog(bodyNode, d) {
  const items = (d && d.items) || [];
  const hook = (d && d.hook) || {};
  bodyNode.appendChild(card(t("l.hooks"), kv([
    [t("l.state"), hook.installed ? badge(t("l.on"), "good") : badge(t("l.off"), "warn")],
    [t("risk.reason"), hook.reason || "-"],
    [t("l.hookFile"), (d && d.file) || "-"],
    [t("l.records"), hook.records || 0],
    [t("l.last"), hook.last || "-"],
  ])));

  const rows = items.slice().reverse();
  bodyNode.appendChild(card(t("l.title"), table([
    { label: t("l.col.time"), key: "time", width: "180px" },
    {
      label: t("l.col.action"),
      width: "130px",
      render: (r) => {
        const wrap = el("div", "xpm-row");
        wrap.appendChild(badge(r.action === "disable" ? t("l.disable") : t("l.enable"),
          r.action === "disable" ? "warn" : "good"));
        if (r.batch) wrap.appendChild(badge(t("l.batch"), "info"));
        return wrap;
      },
    },
    {
      label: t("l.col.target"),
      key: "name",
      render: (r) => {
        const wrap = el("div");
        if (r.names && r.names.length) wrap.appendChild(el("span", "", r.names.join("、")));
        else wrap.appendChild(el("span", "", r.name || "-"));
        if (r.from || r.to) wrap.appendChild(el("div", "xpm-code", (r.from || "") + " → " + (r.to || "")));
        if (r.error || (!r.ok && r.message)) wrap.appendChild(el("div", "xpm-note", r.error || r.message));
        return wrap;
      },
    },
    { label: t("l.col.result"), width: "100px", render: (r) => (r.ok ? badge("OK", "good") : badge(t("l.fail"), "bad")) },
    {
      label: "",
      width: "120px",
      render: (r) => {
        const names = (r.names && r.names.length) ? r.names : (r.name ? [r.name] : []);
        if (!names.length) return "";
        const act = r.action === "disable" ? "enable" : "disable";
        return btn(act === "enable" ? t("l.restore") : t("btn.disable"), "ghost", () => runAction({
          action: act,
          names: act === "disable" ? names : undefined,
          name: act === "disable" ? undefined : (names.length === 1 ? names[0] : undefined),
          ack: (act === "disable" ? "disable " + names.length : "enable " + names.length),
        }));
      },
    },
  ], rows, { emptyText: t("l.empty") })));
}

/* ------------------------------------------------------------------ 动作 */

function riskOf(d, names) {
  const map = {};
  (d.packs || []).forEach((p) => {
    map[p.name] = p;
  });
  const risky = [];
  const safe = [];
  names.forEach((n) => {
    const p = map[n];
    if (!p) {
      safe.push(n);
      return;
    }
    if (packRisk(p) > 0) risky.push(p);
    else safe.push(n);
  });
  return { risky: risky, safe: safe };
}

function oneAction(action, p) {
  if (packRisk(p) === 0) {
    showModal(t("risk.title"), (bodyNode, close) => {
      bodyNode.appendChild(el("div", "xpm-note", (action === "disable" ? t("l.disable") : t("l.enable")) + "：" + p.name));
      bodyNode.appendChild(el("div", "xpm-note", t("p.noRefs") + "；" + t("p.noneWf")));
      bodyNode.appendChild(el("div", "xpm-warnbox", t("risk.restart")));
      const row = el("div", "xpm-row");
      row.appendChild(btn(t("common.cancel"), "ghost", () => close()));
      row.appendChild(btn(t("common.confirm"), "danger", () => {
        close();
        runAction({ action: action, name: p.name, ack: "yes" });
      }));
      bodyNode.appendChild(row);
    });
    return;
  }
  const word = action + " " + p.name;
  showModal(t("risk.title"), (bodyNode, close) => {
    bodyNode.appendChild(el("div", "xpm-warnbox", t("risk.body")));
    const ul = el("ul", "xpm-list");
    if (p.refs_total) {
      ul.appendChild(el("li", "", t("p.refsCount", p.refs_total) + "：" +
        (p.refs || []).slice(0, 4).map((e) => e.from + " (" + e.file + ":" + e.line + ")").join("；")));
    }
    if (p.workflows_total) {
      ul.appendChild(el("li", "", t("p.wfCount", p.workflows_total) + "：" + (p.workflows || []).join("、")));
    }
    if ((p.unknown || []).length) {
      ul.appendChild(el("li", "", t("p.unknownUsed") + "：" + p.unknown.slice(0, 4).map((u) => u.type).join("、")));
    }
    if (p.keep_never) ul.appendChild(el("li", "", t("p.keepNever")));
    if (p.note) ul.appendChild(el("li", "", t("p.note") + "：" + p.note));
    bodyNode.appendChild(ul);
    bodyNode.appendChild(el("div", "xpm-note", t("risk.typeHere")));
    bodyNode.appendChild(el("div", "xpm-code", word));
    const inp = el("input", "xpm-input");
    inp.style.width = "100%";
    bodyNode.appendChild(inp);
    bodyNode.appendChild(el("div", "xpm-note", t("risk.restart")));
    const row = el("div", "xpm-row");
    row.appendChild(btn(t("common.cancel"), "ghost", () => close()));
    row.appendChild(btn(t("common.confirm"), "danger", () => {
      if (inp.value !== word) {
        toast("warn", t("risk.word") + "：" + word);
        return;
      }
      close();
      runAction({ action: action, name: p.name, ack: word });
    }));
    bodyNode.appendChild(row);
  });
}

function batchAction(action, names, d) {
  const r = riskOf(d, names);
  const riskyNames = r.risky.map((p) => p.name);
  const safeNames = r.safe;
  const word = action + " " + names.length + (action === "disable" && riskyNames.length ? " risky" : "");

  showModal(t("risk.title"), (bodyNode, close) => {
    bodyNode.appendChild(el("div", "xpm-warnbox", t("risk.batchNote")));
    if (riskyNames.length) {
      bodyNode.appendChild(el("div", "xpm-note", t("risk.riskyList", riskyNames.length)));
      const ul = el("ul", "xpm-list");
      r.risky.forEach((p) => {
        const reasons = [];
        if (p.refs_total) reasons.push(t("p.refsCount", p.refs_total));
        if (p.workflows_total) reasons.push(t("p.wfCount", p.workflows_total));
        if (p.keep_never) reasons.push(t("p.keepNever"));
        ul.appendChild(el("li", "", p.name + " —— " + reasons.join("；")));
      });
      bodyNode.appendChild(ul);
    }
    bodyNode.appendChild(el("div", "xpm-note", t("risk.safeList", safeNames.length)));
    bodyNode.appendChild(el("div", "xpm-note",
      t("common.name") + "：" + (safeNames.slice(0, 40).join("、") || t("common.none"))));

    function run(list, ackWord) {
      if (!list.length) {
        toast("warn", t("common.empty"));
        return;
      }
      close();
      runAction({
        action: action,
        names: list,
        ack: ackWord || (action + " " + list.length + (action === "disable" && riskyNames.length ? " risky" : "")),
      });
    }

    if (action === "disable" && riskyNames.length && safeNames.length) {
      const row0 = el("div", "xpm-row");
      row0.appendChild(btn(t("risk.excludeRisky", safeNames.length), "", () => run(safeNames, "disable " + safeNames.length)));
      bodyNode.appendChild(row0);
    }

    bodyNode.appendChild(el("div", "xpm-note", t("risk.typeHere")));
    bodyNode.appendChild(el("div", "xpm-code", word));
    const inp = el("input", "xpm-input");
    inp.style.width = "100%";
    bodyNode.appendChild(inp);
    bodyNode.appendChild(el("div", "xpm-note", t("risk.restart")));
    const row = el("div", "xpm-row");
    row.appendChild(btn(t("common.cancel"), "ghost", () => close()));
    row.appendChild(btn(t("common.confirm"), "danger", () => {
      if (inp.value !== word) {
        toast("warn", t("risk.word") + "：" + word);
        return;
      }
      run(names, word);
    }));
    bodyNode.appendChild(row);
  });
}

const ACTION_CHUNK = 40;

async function runAction(payload) {
  try {
    if (!payload.names || !payload.names.length) {
      const res = await apiPost("/action", payload);
      finishAction(payload.action, [payload.name], res.result || {});
      return;
    }
    const names = payload.names.slice();
    const agg = { done: 0, failed: 0, blocked: [], retry: [] };
    for (let i = 0; i < names.length; i += ACTION_CHUNK) {
      const chunk = names.slice(i, i + ACTION_CHUNK);
      const res = await apiPost("/action", { action: payload.action, names: chunk, ack: payload.ack });
      const r = res.result || {};
      if (r.precheck) {
        const bad = (r.results || []).filter((x) => !x.ok);
        const badNames = bad.map((x) => x.name);
        bad.forEach((x) => agg.blocked.push(x));
        agg.failed += bad.length;
        chunk.forEach((n) => {
          if (badNames.indexOf(n) < 0) agg.retry.push(n);
        });
      } else {
        agg.done += r.done || 0;
        agg.failed += r.failed || 0;
        (r.results || []).forEach((x) => {
          if (!x.ok) agg.blocked.push(x);
        });
      }
    }
    if (agg.retry.length) {
      showPrecheckModal(agg, payload);
      return;
    }
    finishAction(payload.action, names, agg);
  } catch (e) {
    toast("error", String(e && e.message ? e.message : e));
    try {
      const j = await apiGet("/log?limit=5");
      showTextModal(t("common.error"), JSON.stringify(j.log, null, 2));
    } catch (e2) { /* 忽略 */ }
  }
}

function showPrecheckModal(agg, payload) {
  showModal(t("risk.blockedTitle"), (bodyNode, close) => {
    bodyNode.appendChild(el("div", "xpm-warnbox", t("risk.stopped")));
    const ul = el("ul", "xpm-list");
    agg.blocked.slice(0, 60).forEach((b) => {
      ul.appendChild(el("li", "", b.name + " —— " + (b.message || t("common.error"))));
    });
    bodyNode.appendChild(ul);
    if (agg.done) bodyNode.appendChild(el("div", "xpm-note", t("risk.partial", agg.done, agg.failed)));
    const row = el("div", "xpm-row");
    row.appendChild(btn(t("common.cancel"), "ghost", () => {
      close();
      finishAction(payload.action, [], agg);
    }));
    row.appendChild(btn(t("risk.skipGo", agg.retry.length), "danger", () => {
      close();
      runAction({ action: payload.action, names: agg.retry, ack: payload.ack });
    }));
    bodyNode.appendChild(row);
  });
}

function finishAction(action, names, r) {
  let done = (r && r.done) || 0;
  let failed = (r && r.failed) || 0;
  let failMsg = "";
  if (r && r.done === undefined && r.failed === undefined && r.ok !== undefined) {
    /* 单个动作：服务端返回的是一条 do_action 记录（只有 ok/message，没有 done/failed） */
    if (r.ok) done = 1;
    else { failed = 1; failMsg = r.message || t("common.error"); }
  }
  if (failed && failMsg) {
    toast("error", failMsg + ((r && r.name) ? "  " + r.name : ""));
  } else if (done || failed) {
    const msg = (done && failed) ? t("risk.partial", done, failed)
      : (action === "disable" ? t("risk.done", done) : t("risk.enableDone", done));
    toast((failed && !done) ? "error" : "success",
      msg + ((names && names.length) ? "  " + names.join("、") : ""));
  }
  S.sel.clear();
  S.loaded.packs = false;
  S.loaded.log = false;
  S.loaded.startup = false;
  S.loaded.workflows = false;
  S.loaded.models = false;
  if (S.tab === "packs") loadTab("packs", true);
  else if (S.tab === "log") loadTab("log", true);
  else renderActive();
}

async function openPath(path) {
  try {
    await apiPost("/open", { path: path });
  } catch (e) {
    toast("warn", String(e && e.message ? e.message : e));
  }
}

/* ------------------------------------------------------------------ 注册 */

if (app && app.registerExtension) {
  app.registerExtension({
    name: "X-WIDE_plugin_model_manager",
    async setup() {
      /* 样式表必须在**任何**入口之前注入：侧边栏、弹窗、提示条全靠它。
         之前只在 openBig()（整页大面板）里注入，结果正常从侧边栏进来时整套 UI 完全没有样式：
         按钮是宿主默认样式、弹窗排在文档流底部被画布盖住 —— 真机实测确认过。 */
      try { injectStyle(); } catch (e) { console.error("[X-WIDE_plugin_model_manager] 注入样式失败：", e); }
      const mgr = app.extensionManager;
      if (!mgr || !mgr.registerSidebarTab) {
        console.warn("[X-WIDE_plugin_model_manager] 这个前端没有 registerSidebarTab，界面不可用；HTTP API 仍然可用。");
        return;
      }
      /* 侧边栏内容单独写成函数：切语言之后要能自己重画一遍（ComfyUI 不会替我们重画） */
      const drawSide = (element) => {
        {
          try { injectStyle(); } catch (e) { /* 已经注入过就忽略 */ }
          clear(element);
          const box = el("div", "xpm-side");
          box.style.padding = "12px 12px 20px";

          /* ① 品牌区：作者自己的 X-WIDE logo（横版，白底卡片；原来那张只有一个 X，
                用户指出「图标不对」）＋ 标题 ＋ 副标题 ＋ 版本号 / 开源协议 ＋ 免责声明 */
          const brand = el("div", "xpm-side-brand");
          try {
            const im = el("img", "xpm-side-logo");
            im.src = PREFIX + "/web/logo_xwide.png";
            im.alt = "X-WIDE";
            im.addEventListener("error", () => {
              /* 横版 logo 取不到时退回方形图标，再取不到就整张去掉，别把侧边栏搞崩 */
              try {
                if (!im.dataset.fallback) {
                  im.dataset.fallback = "1";
                  im.src = PREFIX + "/web/logo_xwide_icon.png";
                  return;
                }
                im.remove();
              } catch (e) { /* 忽略 */ }
            });
            brand.appendChild(im);
          } catch (e) { /* 图片加不上也不能把侧边栏带崩 */ }
          const titleBox = el("div");
          titleBox.appendChild(el("div", "xpm-side-title", t("title")));
          brand.appendChild(titleBox);
          brand.appendChild(el("div", "xpm-side-sub", t("sub")));

          /* 版本号 + 开源协议（点了直接开仓库里的 LICENSE） */
          const meta = el("div", "xpm-side-meta");
          meta.appendChild(badge(xt("sideVer") + " v" + VERSION, "info"));
          try {
            const lic = el("a", "xpm-lic", "⚖ " + xt("licenseName"));
            lic.href = LINKS.license;
            lic.target = "_blank";
            lic.rel = "noreferrer noopener";
            lic.title = xt("licenseTip");
            meta.appendChild(lic);
          } catch (e) {
            meta.appendChild(badge(xt("licenseName"), "plain"));
          }
          brand.appendChild(meta);

          /* 免责声明：授权、担保与「禁用只改目录名」三件事一次说清 */
          brand.appendChild(el("div", "xpm-side-disc", xt("disclaimer")));
          box.appendChild(brand);

          /* ② 作者与链接：作者要求挪到图标下面（原来在最底部，得滚下去才看得到）；
                只要 GitHub 与 B 站两个入口，不要商店入口 */
          const links = el("div", "xpm-card");
          links.appendChild(el("div", "xpm-side-gtitle", xt("sideLinks")));
          const lr = el("div", "xpm-side-row");
          lr.appendChild(linkBtn(xt("linkRepo"), LINKS.repo));
          lr.appendChild(linkBtn(xt("linkBili"), LINKS.author));
          links.appendChild(lr);
          box.appendChild(links);

          /* ③ 自动处理：开关和执行按钮直接放这儿，不用先开完整面板 */
          box.appendChild(autopilotCard({ side: true }));

          /* ③ 常用操作：主按钮独占一行，其余并排等高、宽度统一 */
          const ops = el("div", "xpm-card");
          ops.appendChild(el("div", "xpm-side-gtitle", xt("sideOps")));
          const r1 = el("div", "xpm-side-row");
          r1.appendChild(btn(xt("btnOpenFull"), "primary xpm-wide", openPanel, xt("popoutTip")));
          ops.appendChild(r1);
          const r2 = el("div", "xpm-side-row");
          r2.appendChild(btn(t("btn.report"), "ghost xpm-third", () => genReport()));
          r2.appendChild(btn(t("btn.help"), "ghost xpm-third", () => showHelp()));
          /* 中英切换也放侧边栏一份（完整面板页眉里那个是同一个设置，存 localStorage） */
          r2.appendChild(btn(LANG === "zh" ? "English" : "中文", "ghost xpm-third", () => {
            setLang(LANG === "zh" ? "en" : "zh");
            drawSide(element);
          }));
          ops.appendChild(r2);
          box.appendChild(ops);

          /* 作者与链接已经挪到图标下面（见上面的 ②），这里不再重复一份 */

          element.appendChild(box);
        }
      };

      mgr.registerSidebarTab({
        id: "xwide-plugin-manager",
        icon: "pi pi-box",
        title: "X-WIDE",
        tooltip: t("title"),
        type: "custom",
        render: (element) => drawSide(element),
      });
    },
  });
} else if (STANDALONE) {
  /* 独立窗口里没有侧边栏可点，直接把大页面打开 */
  const boot = () => {
    try {
      openBig();
    } catch (e) {
      console.error("[X-WIDE_plugin_model_manager] 独立窗口启动失败：", e);
    }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
} else {
  console.warn("[X-WIDE_plugin_model_manager] 没有 app.registerExtension：侧边栏入口不可用；" +
    "可以直接打开 " + PREFIX + "/ui，或用 HTTP API。");
}
