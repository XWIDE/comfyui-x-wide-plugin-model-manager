#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom-node pack advisor -- 只读。

对每个自定义节点包给出：
  * 启动开销（读 comfyui.log 的 Prestartup / Import 两张表）
  * 你的工作流到底用没用它（递归扫 workflows/*.json 里的 "type"）
  * 还有哪些【已启用】的包在依赖它（四层证据：import / 动态加载 / 列表声明 / 文档）

模式:
  report                 写出 CustomNode插件顾问报告.md + 控制台摘要（默认）
  deps                   只算依赖关系
  check <包的子串>        单个包：开销 / 用量 / 谁需要它 / 它需要谁 / 是否已禁用
  cache-clear            删掉依赖缓存

硬保证：本脚本绝不改名、移动、删除或写入任何 ComfyUI 目录里的东西，只读；
        所有输出都写在本插件自己的数据目录。
路径全部由 xwide_env 推导（支持 folder_paths / 自动推断 / XWIDE_* 环境变量），
        所以在别人的机器上、别的盘符、别的 ComfyUI 发行版里都能用。
"""
import ast
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import warnings

try:                                    # 作为包的一部分被导入（ComfyUI 加载时）
    from . import xwide_env as E
except ImportError:                     # 被当脚本单独跑（工作区里的探针就是这种）
    import xwide_env as E

# 路径一律从 xwide_env 推导：优先 folder_paths，其次按本插件位置推断，
# 再其次看 XWIDE_* 环境变量，最后退回平台常规位置。跨机器可用，不再写死盘符。
NODES_DIR = E.custom_nodes_dir()
WF_DIR = E.workflows_dir()
LOG = E.log_file()
SERVER = E.server_url()

WORKSPACE = E.data_dir()
REPORT = os.path.join(WORKSPACE, "CustomNode插件顾问报告.md")
OBJ_CACHE = os.path.join(WORKSPACE, "_object_info.json")
CACHE = os.path.join(WORKSPACE, "_pack_advisor_cache.json")
# 依赖扫描缓存：v2 起按【包】增量——记下每个包的源码最新 mtime，只有源码变过的包才重扫。
# v1（只有 built_at，任何文件变新就全量重扫）在 v2 里会被识别为“旧格式”而整体重扫一次。
CACHE_VERSION = 2
CACHE_STATUS = {"file": CACHE, "version": CACHE_VERSION, "exist": False, "format": None,
                "reused": 0, "scanned": 0, "seconds": None, "entries": 0,
                "built_at": None, "write_error": None, "load_error": None}

COST_MIN = 1.5                      # 秒：低于这个开销不值得禁
# 故意不含 .json：目录清单/工作流 json 是元数据，不是依赖声明（ComfyUI-Manager 的
# custom-node-list.json / extension-node-map.json 会把它收录的每个包都“引用”一遍）
DOC_EXT = (".md", ".txt", ".rst", ".toml", ".yaml", ".yml", ".cfg", ".ini")
BROAD_REFS = 12          # 被超过这么多【不同的包】提到 = 生态泛引用，折叠掉
WEAK_DIRS = ("tests", "test", "docs", "doc", "examples", "example", "samples", "workflows", ".github")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".github", ".mypy_cache"}
MAX_FILE = 4 * 1024 * 1024
# 名字太短/太通用的不去做字符串匹配，避免 math / comfymath 这种误报
GENERIC = {
    "comfyui", "comfy", "custom", "nodes", "node", "pack", "plugin", "plugins",
    "extension", "extensions", "suite", "plus", "pro", "lite", "utils", "util",
    "tools", "tool", "kit", "comfyui",
}
DYNAMIC_ATTRS = {"import_module", "find_spec", "reload", "__import__", "load_module", "spec_from_file_location"}
DYNAMIC_NAMES = {"__import__", "import_module", "find_spec"}
DOC_STRONG = re.compile(r"(?i)(requir|depend|need|must|necessar|mandator|install|prerequisit|需要|依赖|必需|前置|必须先|配套)")
TABLE_ROW = re.compile(r"^(?:\[[^\]]+\]\s*)?(\d+(?:\.\d+)?) seconds(?: \((?:IMPORT|PRESTARTUP) FAILED\))?:\s*(.+?)\s*$")


# ---------------------------------------------------------------- 基础

def norm(s: str) -> str:
    s = str(s).lower()
    if s.endswith(".disabled"):
        s = s[:-len(".disabled")]
    return re.sub(r"[^a-z0-9]+", "", s)


def list_packs():
    """-> [(base, path, enabled)]"""
    out = []
    if not os.path.isdir(NODES_DIR):
        return out
    for name in sorted(os.listdir(NODES_DIR)):
        p = os.path.join(NODES_DIR, name)
        if not os.path.isdir(p) or name.startswith(".") or name == "__pycache__":
            continue
        if name.endswith(".disabled"):
            out.append((name[:-len(".disabled")], p, False))
        else:
            out.append((name, p, True))
    return out


# ---------------------------------------------------------------- 插件简介

DESC_CACHE = os.path.join(WORKSPACE, "_pack_desc_cache.json")
DESC_VERSION = 1
DESC_MAX = 160                      # 表格里放得下的长度
DESC_READMES = ("README.md", "readme.md", "README.MD", "README.rst", "README.txt", "README")
DESC_SKIP_HEAD = ("#", "!", "[", "<", "|", "---", "===", "```", ">")
DESC_RX_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
DESC_RX_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _desc_from_pyproject(path):
    """读 pyproject.toml 里 [project] 的 description。不用 tomllib：requires-python 是 3.10。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read(200000)
    except OSError:
        return ""
    m = re.search(r'^\s*description\s*=\s*["\']([^"\']+)["\']\s*$', txt, re.M)
    return (m.group(1) if m else "").strip()


def _desc_from_readme(path):
    """README 第一段像人话的文字（跳过标题、徽章、表格、代码块、引用块）。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read(60000).splitlines()
    except OSError:
        return ""
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(DESC_SKIP_HEAD):
            continue
        s = DESC_RX_LINK.sub(r"\1", DESC_RX_IMG.sub("", s))
        s = re.sub(r"[*_`]+", "", s).strip()
        if len(s) >= 8:
            return s
    return ""


def pack_descriptions(force=False):
    """-> {包名: 一句话简介}。缓存按「源文件 mtime」失效；读不到就留空，不编造。

    来源优先级：pyproject.toml 的 [project] description → README 第一段文字。
    实测本机 186 个启用包里有 184 个能读到，所以界面上直接显示这一列。
    """
    sources = {}
    for base, path, _en in list_packs():
        cand = []
        for fn in ("pyproject.toml",) + DESC_READMES:
            fp = os.path.join(path, fn)
            if os.path.isfile(fp):
                try:
                    cand.append((fn, fp, round(os.path.getmtime(fp), 1)))
                except OSError:
                    pass
        if cand:
            sources[base] = cand
    sig = hashlib.sha1(repr(sorted(sources.items())).encode("utf-8")).hexdigest()
    if not force:
        cached = E.read_json(DESC_CACHE, None)
        if (isinstance(cached, dict) and cached.get("version") == DESC_VERSION
                and cached.get("sig") == sig and isinstance(cached.get("items"), dict)):
            return dict(cached["items"])
    items = {}
    for base, cand in sorted(sources.items()):
        desc = ""
        for fn, fp, _m in cand:
            desc = _desc_from_pyproject(fp) if fn == "pyproject.toml" else _desc_from_readme(fp)
            if desc:
                break
        items[base] = re.sub(r"\s+", " ", desc).strip()[:DESC_MAX] if desc else ""
    try:
        E.write_json_atomic(DESC_CACHE, {"version": DESC_VERSION, "sig": sig,
                                         "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                         "items": items})
    except Exception:
        pass                        # 缓存写不进去也不影响用
    return items


def variants(base: str):
    """一个包名可能被别处写成什么样（去掉 ComfyUI- 前缀等）"""
    vs = set()
    b = base.strip()
    if len(b) >= 6 and norm(b) not in GENERIC:
        vs.add(b)
    # 去掉前缀的短名字太容易撞车（ComfyUI-Manager -> Manager 会命中 "Meta Batch Manager"），
    # 所以只接受 >= 8 个字符的短名：LTXVideo(8)/WanVideoWrapper/RES4LYF 这种才够独特。
    for pre in ("ComfyUI-", "ComfyUI_", "comfyui-", "comfyui_", "Comfy-", "Comfy_", "ComfyUI"):
        if b.lower().startswith(pre.lower()):
            rest = b[len(pre):].strip("-_ ")
            if len(rest) >= 8 and norm(rest) not in GENERIC:
                vs.add(rest)
    return vs


def path_kind(rel, kind):
    """测试/文档/示例目录里的引用降级：那里出现别的包多半不是运行依赖。"""
    low = "\\" + rel.lower().replace("/", "\\") + "\\"
    base = os.path.basename(rel.lower())
    if any(("\\%s\\" % d) in low for d in WEAK_DIRS) or base.startswith("test_") or base.endswith("_test.py") \
            or "document" in base or "readme" in base:
        return "dev" if kind in ("import", "dynamic", "list") else kind
    return kind


def build_matcher(packs):
    """>= 用包名变体建一个大正则；返回 (rx, norm2packs)"""
    var2base = {}
    for base, _p, _e in packs:
        for v in variants(base):
            var2base.setdefault(norm(v), set()).add(base)
    if not var2base:
        return None, {}
    alts = sorted({v for base, _p, _e in packs for v in variants(base)}, key=len, reverse=True)
    rx = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(v) for v in alts) + r")(?![A-Za-z0-9_])", re.I)
    norm2packs = {}
    for base, _p, _e in packs:
        norm2packs.setdefault(norm(base), set()).add(base)
        for v in variants(base):
            norm2packs.setdefault(norm(v), set()).add(base)
    return rx, norm2packs


def packs_in(text, rx, var2base):
    out = set()
    if rx is None or not text:
        return out
    for m in rx.finditer(text):
        for b in var2base.get(norm(m.group(1)), ()):
            out.add(b)
    return out


# ---------------------------------------------------------------- 代码扫描

def _climb(node, parents, stop=4):
    cur, n = node, 0
    while cur in parents and n < stop:
        cur = parents[cur]
        n += 1
        yield cur


def scan_py(path, rel, rx, var2base, res):
    try:
        if os.path.getsize(path) > MAX_FILE:
            return
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    try:
        # 第三方源码经常有 "\d" 这种无效转义，Python 3.13 会在编译期发 SyntaxWarning；
        # 一次全量扫描能在 ComfyUI 日志里刷出几十行 <unknown>:N: SyntaxWarning，屏蔽掉。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return
    lines = src.splitlines()
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                res["imports"].append([a.name, rel, node.lineno])
        elif isinstance(node, ast.ImportFrom):
            if (node.level or 0) == 0 and node.module:
                res["imports"].append([node.module, rel, node.lineno])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            hits = packs_in(node.value, rx, var2base)
            if not hits:
                continue
            kind = "str"
            for anc in _climb(node, parents):
                if isinstance(anc, ast.Call):
                    f = anc.func
                    if (isinstance(f, ast.Attribute) and f.attr in DYNAMIC_ATTRS) or \
                       (isinstance(f, ast.Name) and f.id in DYNAMIC_NAMES):
                        kind = "dynamic"
                        break
                    if kind != "list" and isinstance(f, ast.Attribute) and f.attr in ("get", "pop", "setdefault"):
                        kind = "list"
                if isinstance(anc, ast.Call) and kind != "list":
                    # register_and_count([...]) / register_*([...]) 这类列表声明
                    f = anc.func
                    nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                    if nm.startswith("register") or nm in ("extend", "update", "append"):
                        kind = "list"
                if isinstance(anc, (ast.List, ast.Tuple, ast.Set)):
                    kind = "list"
                    break
                if isinstance(anc, ast.Dict):
                    kind = "list"
                    break
            kind = path_kind(rel, kind)
            text = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
            if len(text) > 220:
                text = text[:217] + "..."
            for dep in hits:
                res["mentions"].append([dep, kind, rel, node.lineno, text])


def scan_text(path, rel, rx, var2base, res):
    try:
        if os.path.getsize(path) > MAX_FILE:
            return
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                if len(line) > 4000:
                    continue
                hits = packs_in(line, rx, var2base)
                if not hits:
                    continue
                kind = path_kind(rel, "doc-strong" if DOC_STRONG.search(line) else "doc")
                text = line.strip()
                if len(text) > 220:
                    text = text[:217] + "..."
                for dep in hits:
                    res["mentions"].append([dep, kind, rel, i, text])
    except OSError:
        return


def scan_pack(base, path, rx, var2base, dependents):
    res = {"imports": [], "mentions": []}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, NODES_DIR)
            if fn.endswith(".py"):
                scan_py(fp, rel, rx, var2base, res)
            elif fn.lower().endswith(DOC_EXT):
                scan_text(fp, rel, rx, var2base, res)
    return res


def newest_source_mtime():
    newest = 0.0
    for root, dirs, files in os.walk(NODES_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py"):
                try:
                    m = os.path.getmtime(os.path.join(root, fn))
                except OSError:
                    continue
                if m > newest:
                    newest = m
    return newest


def pack_source_mtime(path):
    """单个包里所有 .py 的最新 mtime；0.0 表示这个包里没有 .py（或读不到）。

    只 stat 不读内容，195 个包合计约 1 秒（本机有文件过滤驱动，stat 约 100 微秒/次）。
    """
    newest = 0.0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                m = os.path.getmtime(os.path.join(root, fn))
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


CONF = {
    "import":       ("高", "代码里直接 import 了它；禁用后这个 import 会失败，通常整包加载不了。"),
    "dynamic":      ("高", "代码里用 importlib/__import__/find_spec 动态加载；禁用后会报错或静默降级（VRGDG 就这样丢过一个节点族）。"),
    "list":         ("中", "代码里以列表/注册表的形式声明了它（可选节点、兼容包或包装清单）；禁用后这些节点消失，包一般还能加载。"),
    "str":          ("低", "只是代码里出现了这个名字（注释、提示语、路径拼接），多半无关。"),
    "doc":          ("低", "只在文档（README/INSTALL/requirements/配置）里提到，属于说明级，未必是硬依赖。"),
    "doc-strong":   ("中", "文档里明写 requires / 需要 / 依赖 之类字样的那一行提到了它——文档级的依赖声明。"),
    "dev":          ("低", "只在测试/示例/文档/工作流 json 这类非运行路径里出现，基本可忽略。"),
}


def dep_warning(A, base, inc, broad):
    """渲染“谁引用它、引用得可信不可信”。候选清单（第 2 节）和已禁用体检（第 4 节）共用。"""
    hard = [e for e in inc if e["kind"] in ("import", "dynamic", "list")]
    decl = [e for e in inc if e["kind"] == "doc-strong"]
    weak = [e for e in inc if e["kind"] in ("str", "doc", "dev")]
    if not inc:
        b = broad.get(base)
        if b:
            A("- ⚠️ 它被 **%d 个包**在文档里提到过（生态泛引用，已折叠，第三节有汇总）：%s"
              % (b["packs"], "、".join(b["top"][:6])))
            A("  这通常**不是依赖**，而是大家在 README 里写“先装它 / 用管理器装”。")
        else:
            A("- ✅ 没有其它包引用它")
        return
    A("- ⚠️ **依赖警告：%d 处引用**（引用它的都是**启用中**的包）：代码里真 import/显式清单 %d 处，"
      "文档里明写 requires / 需要 的 **%d 处**，纯文档提及 %d 处（后两类要自己点开看一眼）："
      % (len(inc), len(hard), len(decl), len(weak)))
    A("")
    A("  | 谁 | 级别 | 证据 | 后果 |")
    A("  |---|---|---|---|")
    shown = hard[:8] + decl[:6] + weak[:3]
    for e in shown:
        lvl, cons = CONF[e["kind"]]
        A("  | %s | %s | `%s:%s` %s | %s |" %
          (e["dependent"], lvl, e["file"], e["line"], e["text"].replace("|", "/"), cons))
    if len(inc) > len(shown):
        A("  | … | 省略 | 还有 %d 处同类引用（多为别的包的 README/安装说明里提到它） | 参考价值低 |"
          % (len(inc) - len(shown)))
    A("")


# 自动生成的“节点文档库”型包：它几乎会提到每一个包，作为依赖方出现只会制造噪声
NOISE_DEPENDENTS = {"comfyui-nodes-docs"}


def derive_edges(raw, packs):
    """把“原始扫描结果”推导成依赖边。

    单独拆出来是因为缓存里存的是 raw（源码里到底提到了谁），改过滤/置信度规则时
    不必再花 8 分钟重扫，只需重新推导。
    """
    norm2base = norm2base_of(packs)
    edges = {}
    for base, r in raw.items():
        if base in NOISE_DEPENDENTS:
            continue
        for mod, rel, line in r["imports"]:
            for cand in (mod, mod.split(".")[0]):
                for dep in norm2base.get(norm(cand), ()):
                    if dep == base:
                        continue
                    edges.setdefault(dep, []).append(
                        {"dependent": base, "kind": "import", "file": rel, "line": line,
                         "text": ("import %s" % mod)})
        for dep, kind, rel, line, text in r["mentions"]:
            if dep == base:
                continue
            edges.setdefault(dep, []).append(
                {"dependent": base, "kind": kind, "file": rel, "line": line, "text": text})
    return edges, norm2base


def build_edges(packs, use_cache=True):
    rx, var2base = build_matcher(packs)
    alts = sorted({v for base, _p, _e in packs for v in variants(base)})
    needles_hash = hashlib.sha256("\n".join(alts).encode("utf-8")).hexdigest()[:16]
    CACHE_STATUS.update({"exist": os.path.exists(CACHE), "format": None,
                         "load_error": None, "write_error": None,
                         "reused": 0, "scanned": 0, "entries": 0})
    # 每个包的“源码最新 mtime”：这一步只 stat 不读，约 1 秒，换来“只重扫变过的包”
    mtimes = {base: pack_source_mtime(path) for base, path, _e in packs}
    raw = {}
    if use_cache and CACHE_STATUS["exist"]:
        try:
            d = json.load(open(CACHE, encoding="utf-8"))
            old, old_m = d.get("raw") or {}, d.get("pack_mtime") or {}
            CACHE_STATUS["format"] = d.get("version") or 1
            if d.get("version") == CACHE_VERSION and old_m and d.get("needles_hash") == needles_hash:
                for base, _p, _e in packs:
                    r = old.get(base)
                    if r is not None and old_m.get(base, -1.0) >= mtimes.get(base, 0.0):
                        raw[base] = r          # 这个包没动过，直接用上次的扫描结果
                CACHE_STATUS["reused"] = len(raw)
                CACHE_STATUS["built_at"] = d.get("built_at")
                sys.stderr.write("[deps] 缓存可用：复用 %d/%d 个包的扫描结果，需重扫 %d 个\n"
                                 % (len(raw), len(packs), len(packs) - len(raw)))
            else:
                sys.stderr.write("[deps] 缓存不吃：%s，重新扫全部 %d 个包\n"
                                 % ("旧格式（v1）" if d.get("version") != CACHE_VERSION
                                    else "包的清单变了（装/删/改名过插件）", len(packs)))
        except Exception as e:
            CACHE_STATUS["load_error"] = "%s: %s" % (type(e).__name__, e)
            sys.stderr.write("[deps] 缓存不可用: %s\n" % CACHE_STATUS["load_error"])
    t0 = time.time()
    todo = []
    for base, path, enabled in packs:
        if base in raw:
            continue
        if base in NOISE_DEPENDENTS:
            raw[base] = {"imports": [], "mentions": []}
            continue
        todo.append((base, path, enabled))
    total = len(todo)
    if total:
        sys.stderr.write("[deps] 开始扫描 %d 个包的源码（为了不再刷屏，进度每 25 个包一行）\n" % total)
        sys.stderr.flush()
    for i, (base, path, enabled) in enumerate(todo, 1):
        if i == 1 or i % 25 == 0 or i == total:
            sys.stderr.write("[deps] ... %d/%d（已用 %.0fs）\n" % (i, total, time.time() - t0))
            sys.stderr.flush()
        try:
            raw[base] = scan_pack(base, path, rx, var2base, None)
        except Exception as e:      # 单个包读坏不该拖垮整轮分析
            sys.stderr.write("[deps] 扫描 %s 出错：%r（按“没有引用”处理）\n" % (base, e))
            raw[base] = {"imports": [], "mentions": []}
    if use_cache and total:
        # 先写临时文件再 os.replace，避免写一半被读到半截 json
        tmp = CACHE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": CACHE_VERSION, "needles_hash": needles_hash,
                           "built_at": time.time(), "seconds": round(time.time() - t0, 1),
                           "pack_mtime": mtimes, "raw": raw}, fh, ensure_ascii=False)
            os.replace(tmp, CACHE)
            CACHE_STATUS["exist"] = True
        except OSError as e:
            # 以前这里静默吞掉，于是“每次重启都要等 2 分半”而没人知道为什么——现在写进状态和日志
            CACHE_STATUS["write_error"] = "%s: %s" % (type(e).__name__, e)
            sys.stderr.write("[deps] 缓存写盘失败（本次结果照常，但下次重启还得重扫）：%s\n"
                             % CACHE_STATUS["write_error"])
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    CACHE_STATUS.update({"scanned": total, "entries": len(raw), "format": CACHE_VERSION,
                         "seconds": round(time.time() - t0, 1)})
    edges, norm2base = derive_edges(raw, packs)
    # 去重
    for dep in list(edges):
        seen, keep = set(), []
        for e in edges[dep]:
            k = (e["dependent"], e["kind"], e["file"], e["line"])
            if k in seen:
                continue
            seen.add(k)
            keep.append(e)
        edges[dep] = sorted(keep, key=lambda e: {"import": 0, "dynamic": 1, "list": 2, "doc-strong": 3, "doc": 4, "str": 5, "dev": 6}[e["kind"]])
    # 生态泛引用：被很多【不同的包】提到的名字（README 里的安装说明、兼容清单）折叠掉，
    # 否则 ComfyUI-Manager 会被几百条文档命中，把真正的依赖淹没掉
    broad = {}
    for dep in list(edges):
        deps = sorted({e["dependent"] for e in edges[dep]})
        if len(deps) > BROAD_REFS:
            broad[dep] = {"packs": len(deps), "refs": len(edges[dep]), "top": deps[:12]}
            del edges[dep]
    reused = CACHE_STATUS.get("reused", 0)
    blob = {"needles_hash": needles_hash, "seconds": round(time.time() - t0, 1),
            "cache": total == 0,
            "scanned": total, "reused": reused, "cache_info": dict(CACHE_STATUS),
            "packs": {b: {"enabled": e, "imports": len(raw[b]["imports"]), "mentions": len(raw[b]["mentions"])}
                      for b, _p, e in packs},
            "broad": broad}
    sys.stderr.write("[deps] 完成：重扫 %d 个、复用 %d 个，%.1fs，%d 个被依赖的包%s\n"
                     % (total, reused, time.time() - t0, len(edges),
                        "（全部来自缓存）" if not total else ""))
    return edges, norm2base, blob


def norm2base_of(packs):
    m = {}
    for base, _p, _e in packs:
        m.setdefault(norm(base), set()).add(base)
    return m


# ---------------------------------------------------------------- 日志

def parse_log():
    out = {"file": LOG, "mtime": None, "started": None, "gui_ready": None, "server_at": None,
           "prestartup": {}, "imports": {}, "failed": {}, "degrade": []}
    if not os.path.exists(LOG):
        return out
    out["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(LOG)))
    mode = None
    try:
        lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return out
    for ln in lines:
        if "Prestartup times for custom nodes:" in ln:
            mode = "pre"; continue
        if "Import times for custom nodes:" in ln:
            mode = "imp"; continue
        m = TABLE_ROW.match(ln)
        if m and mode:
            secs, target = float(m.group(1)), m.group(2)
            name = os.path.basename(target.rstrip("\\/ "))
            if "FAILED" in ln:
                out["failed"][name] = secs
            elif mode == "pre":
                out["prestartup"][name] = out["prestartup"].get(name, 0.0) + secs
            else:
                out["imports"][name] = out["imports"].get(name, 0.0) + secs
            continue
        ts = re.match(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", ln)
        if ts:
            # started = 这一轮启动里第一条带时间戳的日志（≈ ** ComfyUI startup time 那行）
            if out["started"] is None:
                out["started"] = ts.group(1)
            if "Starting server" in ln:
                out["server_at"] = ts.group(1)
            if "To see the GUI go to" in ln:
                out["gui_ready"] = ts.group(1)
        if re.search(r"(?i)(no module named|failed to import|failed submodule|will be unavailable|not loaded|ModuleNotFoundError)", ln):
            out["degrade"].append(ln.strip()[:300])
    return out


# ---------------------------------------------------------------- 工作流

def load_object_info():
    try:
        with urllib.request.urlopen(SERVER + "/object_info", timeout=8) as r:
            data = r.read()
        obj = json.loads(data.decode("utf-8"))
        # 只在新数据更全的时候覆盖快照：抓到一个“半残”的 /object_info
        # （比如服务刚起来、自定义节点还没注册完）不该把好快照弄坏。
        try:
            old = len(json.load(open(OBJ_CACHE, encoding="utf-8"))) if os.path.exists(OBJ_CACHE) else 0
        except Exception:
            old = 0
        if not old or len(obj) >= old:
            with open(OBJ_CACHE, "wb") as f:
                f.write(data)
        return obj, "实时抓取 " + time.strftime("%Y-%m-%d %H:%M:%S"), True
    except Exception as e:
        if os.path.exists(OBJ_CACHE):
            return (json.load(open(OBJ_CACHE, encoding="utf-8")),
                    "缓存文件 %s（%s，抓不到运行中的实例：%s）" %
                    (os.path.basename(OBJ_CACHE),
                     time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(OBJ_CACHE))), e),
                    False)
        return None, "没有 /object_info（服务没起且无缓存）：%s" % e, False


def snapshot_staleness():
    """-> (快照文件的 mtime 或 None, 比快照更新的 custom_nodes 顶层条目)

    /object_info 是“运行中的实例当时注册了哪些节点”。快照之后新装/恢复/禁用过的包，
    在快照里当然看不到——那会让第四节把它们的节点误判成“没注册”。所以必须如实标出来。
    """
    try:
        mt = os.path.getmtime(OBJ_CACHE)
    except OSError:
        return None, []
    newer = []
    try:
        names = sorted(os.listdir(NODES_DIR))
    except OSError:
        return mt, []
    for name in names:
        if name in SKIP_DIRS:
            continue
        try:
            if os.path.getmtime(os.path.join(NODES_DIR, name)) > mt:
                newer.append(name)
        except OSError:
            pass
    return mt, newer


def node_to_packs(obj):
    m = {}
    for node, info in (obj or {}).items():
        mod = (info or {}).get("python_module") or ""
        if not mod.startswith("custom_nodes."):
            continue
        parts = mod.split(".")
        if len(parts) < 2:
            continue
        folder = parts[1]
        base = folder[:-len(".disabled")] if folder.endswith(".disabled") else folder
        m.setdefault(base, set()).add(node)
    return m


TYPE_RX = re.compile(r'"type"\s*:\s*"([^"]+)"')
# 前端虚拟节点（不是后端注册的节点，/object_info 里当然没有）——别当成“你丢了的功能”
VIRTUAL_TYPES = {"Reroute", "Note", "PrimitiveNode", "Bookmark", "Reroute (rgthree)",
                 "GetNode", "SetNode", "Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)",
                 "Anything Everywhere", "Anything Everywhere?", "Anything Everywhere3",
                 "MarkdownNote", "Label (rgthree)", "PixaromaLabel"}
# 数据类型（插槽上的 type），永远不是节点类名
DATA_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "NUMBER", "COMBO", "MODEL", "CLIP", "VAE",
              "CONDITIONING", "LATENT", "IMAGE", "MASK", "CONTROL_NET", "UPSCALE_MODEL",
              "LORA_STACK", "SAMPLER", "SIGMAS", "GUIDER", "NOISE", "CLIP_VISION", "STYLE_MODEL",
              "GLIGEN", "PHOTOMAKER", "IMAGEUPLOAD", "WEBCAM", "AUDIO", "VIDEO", "SEGS",
              "BASIC_PIPE", "PIPE", "CLIP_VISION_OUTPUT", "COMFY_DYNAMICCOMBO_V3", "*",
              "EASY_PROMPT_STYLES", "QWEN_TE_SKILL"}
UUID_RX = re.compile(r"\A[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")


def _collect_node_types(obj, out):
    """只收“看起来是节点对象”的 type。

    节点对象一定还有 pos/size/order/widgets_values/mode 这些字段；插槽对象（inputs/outputs）
    只有 type/name/links，而它的 type 是 **数据类型**（CONDITIONING、LATENT、STRING…），
    不过滤的话会把数据类型当成节点类型。
    """
    if isinstance(obj, dict):
        t = obj.get("type")
        if isinstance(t, str) and any(k in obj for k in ("pos", "size", "widgets_values", "order", "mode", "flags")):
            out.add(t)
        for v in obj.values():
            _collect_node_types(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_node_types(v, out)


def _split_subgraphs(data):
    """新前端把子图定义放在顶层 definitions.subgraphs[] 里。

    返回 (子图 id 集合, 子图内部的真节点列表, 去掉 definitions 之后的文档)。
    子图 id 会作为实例节点的 `type` 出现，必须排除；子图定义自己的 inputs/outputs
    是带 pos 的“伪插槽”，它们的 type 是数据类型，所以只走它的 nodes。
    """
    ids, nodes, body = set(), [], data
    defs = data.get("definitions") if isinstance(data, dict) else None
    if isinstance(defs, dict):
        body = {k: v for k, v in data.items() if k != "definitions"}
        for sg in defs.get("subgraphs") or []:
            if not isinstance(sg, dict):
                continue
            if isinstance(sg.get("id"), str):
                ids.add(sg["id"])
            for nd in sg.get("nodes") or []:
                nodes.append(nd)
    return ids, nodes, body


def scan_workflows():
    """-> {pack: [wf, ...]}, {type: [wf,...]}, 文件数"""
    pack_use, type_use, n = {}, {}, 0
    if not os.path.isdir(WF_DIR):
        return pack_use, type_use, n
    for root, dirs, files in os.walk(WF_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(root, fn)
            try:
                if os.path.getsize(fp) > MAX_FILE:
                    continue
                txt = open(fp, encoding="utf-8-sig", errors="replace").read()
            except OSError:
                continue
            n += 1
            try:
                data = json.loads(txt)
                sub_ids, sub_nodes, body = _split_subgraphs(data)
                types = set()
                _collect_node_types(body, types)
                for nd in sub_nodes:
                    _collect_node_types(nd, types)
                types -= sub_ids
            except Exception:
                types = set(TYPE_RX.findall(txt))   # 解析失败就退回正则（下面还会再过滤）
            types -= VIRTUAL_TYPES
            types = {t for t in types if t not in DATA_TYPES and not UUID_RX.match(t)}
            for t in types:
                type_use.setdefault(t, []).append(fn)
    return pack_use, type_use, n


def locate_types_in_disabled(unknown, packs):
    """工作流里没注册的节点类型，逐个在【已禁用】的包里找它出现在哪 -> {type: [(pack, file, line)]}"""
    cand = [t for t in unknown if len(t) >= 6 and re.search(r"[A-Z_]", t)]
    if not cand:
        return {}
    rx = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(t) for t in sorted(cand, key=len, reverse=True)) + r")(?![A-Za-z0-9_])")
    hits = {}
    for base, path, enabled in packs:
        if enabled:
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    if os.path.getsize(fp) > MAX_FILE:
                        continue
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        for i, line in enumerate(fh, 1):
                            for m in rx.finditer(line):
                                hits.setdefault(m.group(1), []).append(
                                    (base, os.path.relpath(fp, NODES_DIR), i))
                except OSError:
                    continue
    return hits


# ---------------------------------------------------------------- 报告

def fmt_secs(x):
    return ("%.1f" % x) if x < 100 else ("%.0f" % x)


def cost_of(base, log):
    c = 0.0
    got = []
    for tab, label in ((log["prestartup"], "prestartup"), (log["imports"], "import")):
        for k, v in tab.items():
            if norm(k) == norm(base) or norm(k) == norm(base) + "disabled":
                c += v
                got.append("%s %.1fs" % (label, v))
    return c, " + ".join(got)


DISABLED_NOTE = ("- 目录名以 `.disabled` 结尾 = ComfyUI 自己会跳过（`folder_paths`/`nodes.py` 都过滤），"
                 "改回来就恢复；`python\\Lib\\site-packages` 里的依赖库不在这里，禁用它不会删库。")

# 光看“耗时 + 工作流没用到”会误伤这两类包，所以单独标注（不是自动判断，是写死的常识）
KEEP_NEVER = {"ComfyUI-Manager"}
NOTES = {
    "ComfyUI-Manager": "基础设施：管理器本体（网页里装/禁/更新节点的入口）。它 prestartup 的二十多秒里，"
                       "绝大部分是 360 拖慢的文件读取和启动 pip 子进程，不是它自己的算法。不建议动。",
    "comfyui_llm_party": "你在本轮明确要求保留（“不能禁用”）。这里只是把开销列出来。",
    "ComfyUI-QwenImageLoraLoader": "它的开销几乎全是 import torch/transformers——ComfyUI 后面本来也要 import 这两个，"
                                   "所以禁掉它实际省不到几秒。",
    "was-node-suite-comfyui": "它的耗时里有一部分是启动时跑 `pip freeze`（已由“修改 7”修掉），本次日志是修改生效前的。",
    "comfyui-preview-video-monitor": "同 pygame 那条：修改 3（shim）已经吃掉了它相关的那部分开销。",
}


def build_report():
    packs = list_packs()
    enabled = [p for p in packs if p[2]]
    disabled = [p for p in packs if not p[2]]
    log = parse_log()
    obj, obj_src, fresh = load_object_info()
    n2p = node_to_packs(obj)
    _pu, type_use, nwf = scan_workflows()
    used_packs = set()
    pack_wf = {}
    for t, wfs in type_use.items():
        for base in n2p.get(t, ()):  # 注册在案的节点类型 -> 直接归属
            used_packs.add(base)
            pack_wf.setdefault(base, set()).update(wfs)
    demo_only = {}
    vrgdg = {}
    for t, wfs in type_use.items():
        if t in (obj or {}):
            continue
        # 未注册类型：按“节点显示名/类名”与包的注册表对不上，只做记录
        demo_only.setdefault(t, wfs)

    edges, norm2base, _blob = build_edges(packs)
    broad = _blob.get("broad", {})
    unknown_hits = locate_types_in_disabled(set(demo_only), packs)

    L = []
    A = L.append
    A("# 自定义节点包顾问报告（只读）")
    A("")
    A("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    A("- 日志：`%s`（最后写入 %s；最近一次启动 %s，GUI 就绪 %s）" %
      (log["file"], log["mtime"], log["started"] or "?", log["gui_ready"] or "?"))
    A("- 节点清单：`%s`" % (obj_src or "无"))
    A("- 工作流：`%s`，共 %d 个 json" % (WF_DIR, nwf))
    A("- 包：%d 个（启用 %d，已禁用 %d）" % (len(packs), len(enabled), len(disabled)))
    A("")
    A("> 这个脚本只读：不改名、不移动、不删除、不写入任何 ComfyUI 目录。")
    A("")
    A("## 一、启动开销最大的包（来自最近一次启动的日志）")
    A("")
    A("| 包 | 本次启动耗时 | 明细 | 状态 |")
    A("|---|---|---|---|")
    rows = []
    for base, path, en in packs:
        c, det = cost_of(base, log)
        if c <= 0:
            continue
        rows.append((c, base, det, "启用" if en else "**已禁用**"))
    # 日志里有、但目录已不在的表项
    known = {norm(b) for b, _p, _e in packs}
    for k, v in list(log["imports"].items()) + list(log["prestartup"].items()):
        if norm(k) not in known:
            rows.append((v, k + "（日志里有、目录里没找到）", "%.1fs" % v, "-"))
    for c, base, det, st in sorted(rows, reverse=True)[:20]:
        A("| %s | %s s | %s | %s |" % (base, fmt_secs(c), det or "-", st))
    A("")
    tot_imp = sum(log["imports"].values())
    tot_pre = sum(log["prestartup"].values())
    A("日志合计：prestartup %.1f s（%d 项）＋ 节点 import %.1f s（%d 项）＝ %.1f s；"
      "IMPORT FAILED %d 个%s" % (tot_pre, len(log["prestartup"]), tot_imp, len(log["imports"]),
                                tot_pre + tot_imp, len(log["failed"]),
                                ("：" + "、".join(sorted(log["failed"]))) if log["failed"] else ""))
    A("")

    A("## 二、开销 ≥ %.1f s、而且你的工作流里没用到的包（候选清单，**不是**“建议禁用”）" % COST_MIN)
    A("")
    A("> ⚠️ **“耗时”不等于“禁掉能省下的时间”。** 包之间的 import 有大量重叠（很多包都会拖起 torch、")
    A("> transformers、numpy 一类的公共库），所以禁掉一个 8 s 的包，实际省下的往往只有几秒；")
    A("> 而且“工作流没用到它的节点”**不等于**“你不需要它”（第 4 节会检查已禁用包有没有被工作流或其它包用到）。")
    A("")
    if not fresh:
        A("> ⚠️ 这两张表是**最近一次启动**的日志，而你刚恢复过包：恢复的包要**下次重启**才会重新出现在")
        A("> `/object_info` 和这张表里。也就是说“某个包没在表里”≠“它没开销”。")
        A("")
    A(DISABLED_NOTE)
    A("")
    cands = []
    for base, path, en in packs:
        if not en:
            continue
        c, det = cost_of(base, log)
        if c < COST_MIN:
            continue
        if base in used_packs:
            continue
        cands.append((c, base, det))
    if not cands:
        A("没有符合条件的包。")
    for c, base, det in sorted(cands, reverse=True):
        inc = [e for e in edges.get(base, []) if any(e["dependent"] == b for b, _p, en in packs if en)]
        A("### %s（%.1f s）%s" % (base, c, "  ⛔ 不建议动" if base in KEEP_NEVER else ""))
        A("")
        if base in NOTES:
            A("> **备注**：%s" % NOTES[base])
            A("")
        A("- 开销明细：%s" % (det or "-"))
        A("- 注册节点数：%d" % len(n2p.get(base, ())))
        A("- 工作流用到它的节点：**没有**（扫了 %d 个工作流 json，递归找 \"type\"）" % nwf)
        dep_warning(A, base, inc, broad)
        if log["degrade"]:
            dl = [x for x in log["degrade"] if norm(base) and base.lower() in x.lower()]
            if dl:
                A("- 日志里与它有关的告警：")
                for x in dl[:5]:
                    A("  - `%s`" % x)
        A("")

    A("## 三、依赖关系总表（谁需要谁）")
    A("")
    A("四层证据的解释：")
    A("")
    A("| 级别 | 形态 | 说明 |")
    A("|---|---|---|")
    for k in ("import", "dynamic", "list", "doc-strong", "doc", "str", "dev"):
        A("| %s | %s | %s |" % (CONF[k][0], k, CONF[k][1]))
    A("")
    A("（`%s` 这类“自动生成的节点文档库”已被忽略：它几乎会提到每一个包，作为引用方没有信息量。）"
      % "、".join(sorted(NOISE_DEPENDENTS)))
    A("")
    if broad:
        A("### 被很多个包同时提到、已折叠的名字（生态泛引用）")
        A("")
        A("这类名字（比如 `ComfyUI-Manager`）在别的包的 README 里当“安装方法”被提了几百次，")
        A("列出来只会淹没真正的依赖，所以只给汇总：")
        A("")
        A("| 名字 | 提到它的包数 | 引用条数 | 前几个 |")
        A("|---|---|---|---|")
        for d, info in sorted(broad.items(), key=lambda kv: -kv[1]["packs"]):
            A("| %s | %d | %d | %s |" % (d, info["packs"], info["refs"], "、".join(info["top"][:6])))
        A("")
    A("| 被依赖的包 | 引用它的包（级别） | 条数 |")
    A("|---|---|---|")
    for dep in sorted(edges, key=lambda d: (-len(edges[d]), d)):
        refs = []
        for e in edges[dep]:
            lvl = CONF[e["kind"]][0]
            tag = "%s(%s)" % (e["dependent"], lvl)
            if tag not in refs:
                refs.append(tag)
        A("| %s | %s | %d |" % (dep, "、".join(refs[:10]) + ("…" if len(refs) > 10 else ""), len(edges[dep])))
    A("")

    A("## 四、已禁用包的体检（“我是不是禁错了”）")
    A("")
    snap_mt, newer = snapshot_staleness()
    stale = bool(newer)
    if stale:
        A("> ⚠️ **这一节的“节点类型”栏现在不可全信**：节点归属靠运行中的 `/object_info` 快照，"
          "用的是 `%s`（%s）；而之后有 **%d** 个 `custom_nodes` 顶层条目变动过（%s%s）。"
          "快照之后新装 / 刚恢复 / 刚禁用的包，它的节点在那份快照里查不到，会被算成“没注册”。"
          "**重启一次 ComfyUI 后再跑本脚本**（能连上就会自动抓最新快照），这一栏才准。"
          % (os.path.basename(OBJ_CACHE), time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap_mt)),
             len(newer), "、".join(newer[:6]), "…" if len(newer) > 6 else ""))
        A("")
    for base, path, en in packs:
        if en:
            continue
        inc = [e for e in edges.get(base, []) if any(e["dependent"] == b for b, _p, e2 in packs if e2)]
        A("### %s" % base)
        A("")
        dep_warning(A, base, inc, broad)
        tused = {t: type_use[t] for t in type_use if base in n2p.get(t, ())}
        if tused:
            A("- ⚠️ **硬证据：你的工作流用到了它的 %d 个节点类型**（它就是被这个包提供的，多半是禁错了）：" % len(tused))
            for t, wfs in sorted(tused.items())[:10]:
                A("  - `%s` ← %s" % (t, "、".join(sorted(set(wfs))[:3])))
            if len(tused) > 10:
                A("  - …（还有 %d 个）" % (len(tused) - 10))
        th = {}
        for t, hs in unknown_hits.items():
            for (b, f, ln) in hs:
                if b == base:
                    th.setdefault(t, []).append("%s:%s" % (f, ln))
        if th:
            A("- %s你的工作流里有 %d 个**没注册的节点类型**只出现在这个包里（可能就是你禁掉的功能，也可能只是快照过期）："
              % ("（低可信，快照已过期）" if stale else "", len(th)))
            for t, ev in sorted(th.items())[:20]:
                A("  - `%s` ← %s" % (t, ev[0]))
        A("")
    A("### 4.1 工作流里没注册、也没在任何已禁用包源码里找到的节点类型")
    A("")
    orphan = sorted(set(demo_only) - set(unknown_hits))
    if not orphan:
        A("- 没有。✅")
    else:
        A("这 %d 个类型既不在运行中的节点清单里，也不在任何已禁用包的 `.py` 里出现。" % len(orphan))
        A("常见原因：**快照过期**（包是快照之后装的）、**纯前端/JS 节点**（后端清单里本来就没有）、")
        A("或这个工作流来自**别的机器/别的整合包**。**不是**“禁掉某个包的证据”。")
        A("")
        for t in orphan:
            A("- `%s` ← %s" % (t, "、".join(sorted(set(type_use[t]))[:3])))
    A("")
    if unknown_hits:
        A("（上面这些“没注册的节点类型”一共 %d 个，逐个在已禁用包的源码/文档里找过，命中的才算。）"
          % len(unknown_hits))
        A("")

    A("## 五、边界与不确定性（请务必看）")
    A("")
    A("1. **静态扫描不是运行时**。第 2 节的“工作流没用到”＝你**保存在 `workflows/` 里的** json 里没出现它的节点类型；")
    A("   你用 API 脚本、临时拖拽没保存的、或别人发来的工作流，这里都看不到。")
    A("2. **依赖证据的可信度不同**：`import`/`dynamic` 是硬的（禁了会报错或静默降级）；")
    A("   `list` 多为可选声明；`doc-strong`/`doc` 只是文档提到，必须点开 `file:line` 看一眼原文再决定；")
    A("   `dev` 是测试/示例/文档目录里的引用，基本可以忽略（已自动降级）。")
    A("   另外：被超过 %d 个不同的包提到的名字会被折叠（生态泛引用），见第三节。" % BROAD_REFS)
    A("3. **节点类型归属靠运行中的 `/object_info`**：所以刚恢复/刚禁用的包要下次重启才对得上。%s" %
      ("" if fresh else "本报告用的是缓存的快照，注意时间戳。"))
    A("4. 本报告**不含**“这个包你还需不需要”的判断——只有开销、用量和依赖这三类可核查的证据。")
    A("")
    A("---")
    A("")
    A("附：依赖缓存 `_pack_advisor_cache.json`（删掉、改名或某个包的源码变新都会自动重扫——"
      "全量重扫要读所有包的全部源码+文档，本次耗时见命令行输出）；")
    A("命令行：`python _pack_advisor.py check <包的子串>` 可单独看一个包。")
    A("")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return REPORT, packs, edges, log, cands, unknown_hits


def cmd_check(pat):
    packs = list_packs()
    hits = [p for p in packs if pat.lower() in p[0].lower()]
    if not hits:
        print("没有匹配 %r 的包" % pat)
        return 1
    log = parse_log()
    edges, _n2b, _b = build_edges(packs)
    obj, obj_src, _f = load_object_info()
    n2p = node_to_packs(obj)
    _pu, type_use, nwf = scan_workflows()
    used = set()
    for t in type_use:
        for b in n2p.get(t, ()):
            used.add(b)
    for base, path, en in hits:
        c, det = cost_of(base, log)
        print("=" * 72)
        print("包: %s%s" % (base, "" if en else "   [已禁用 .disabled]"))
        print("  启动开销 : %.1f s %s" % (c, ("(%s)" % det) if det else ""))
        print("  注册节点 : %d 个" % len(n2p.get(base, ())))
        print("  工作流   : %s" % ("用到了" if base in used else "没用到（%d 个 json 里没出现它的节点类型）" % nwf))
        inc = [e for e in edges.get(base, []) if any(e["dependent"] == b for b, _p, e2 in packs if e2 and b != base)]
        print("  谁需要它 : %d 处" % len(inc))
        for e in inc:
            lvl, cons = CONF[e["kind"]]
            print("     [%s] %-26s %s:%s  %s" % (lvl, e["dependent"], e["file"], e["line"], e["text"][:110]))
        out = []
        for dep, es in edges.items():
            for e in es:
                if e["dependent"] == base:
                    out.append((dep, e))
        print("  它需要谁 : %d 处" % len(out))
        for dep, e in out[:20]:
            lvl, _c = CONF[e["kind"]]
            print("     [%s] %-26s %s:%s  %s" % (lvl, dep, e["file"], e["line"], e["text"][:110]))
    return 0


def main(argv):
    mode = (argv[1] if len(argv) > 1 else "report").lower()
    if mode == "cache-clear":
        if os.path.exists(CACHE):
            os.remove(CACHE)
            print("已删除 %s" % CACHE)
        else:
            print("没有缓存文件")
        return 0
    if mode == "deps":
        packs = list_packs()
        edges, _m, blob = build_edges(packs)
        for dep in sorted(edges, key=lambda d: (-len(edges[d]), d)):
            print("\n%s  <-  %d 条" % (dep, len(edges[dep])))
            for e in edges[dep][:8]:
                print("   [%s] %-26s %s:%s  %s" % (CONF[e["kind"]][0], e["dependent"],
                                                  e["file"], e["line"], e["text"][:100]))
        print("\n共 %d 个被引用的包；耗时 %.1fs（缓存 %s）" % (len(edges), blob.get("seconds", 0), CACHE))
        return 0
    if mode == "check":
        if len(argv) < 3:
            print("用法: python _pack_advisor.py check <包的子串>")
            return 2
        return cmd_check(argv[2])
    path, packs, edges, log, cands, unknown_hits = build_report()
    print("报告已写出: %s" % path)
    print("包 %d 个（启用 %d / 已禁用 %d）；依赖边覆盖 %d 个被依赖的包" %
          (len(packs), sum(1 for p in packs if p[2]), sum(1 for p in packs if not p[2]), len(edges)))
    print("优先候选（没用到 + 开销≥%.1fs）: %s" %
          (COST_MIN, "、".join("%s %.1fs" % (b, c) for c, b, _d in sorted(cands, reverse=True)) or "无"))
    enabled = {b for b, _p, en in packs if en}
    hard, decl = {}, {}
    for b, _p, en in packs:
        if en:
            continue
        h = [e for e in edges.get(b, []) if e["dependent"] in enabled
             and e["kind"] in ("import", "dynamic", "list")]
        d = [e for e in edges.get(b, []) if e["dependent"] in enabled and e["kind"] == "doc-strong"]
        if h:
            hard[b] = len(h)
        elif d:
            decl[b] = len(d)
    if hard:
        print("依赖警告: %d 个已禁用包还在被【启用中】的包在代码里引用（很可能禁错了，见报告第四节）: %s" %
              (len(hard), "、".join("%s(%d 处)" % (b, n) for b, n in sorted(hard.items(), key=lambda kv: -kv[1]))))
    else:
        print("依赖警告: 没有已禁用包还在被启用中的包在代码里引用 ✅")
    if decl:
        print("       文档级声明: %d 个已禁用包被文档明写 requires/需要（不一定错，自己看一眼）: %s" %
              (len(decl), "、".join("%s(%d 处)" % (b, n) for b, n in sorted(decl.items(), key=lambda kv: -kv[1]))))
    print("禁错了的警报: %d 个节点类型只在已禁用包里出现（详见报告第四节）" % len(unknown_hits))
    _mt, _newer = snapshot_staleness()
    if _newer:
        print("  ⚠️ 节点清单快照已过期：快照 %s 之后有 %d 个 custom_nodes 条目变动过（%s%s）"
              % (time.strftime("%m-%d %H:%M", time.localtime(_mt)) if _mt else "?",
                 len(_newer), "、".join(_newer[:4]), "…" if len(_newer) > 4 else ""))
        print("     这一栏要重启 ComfyUI 后再跑才准。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
