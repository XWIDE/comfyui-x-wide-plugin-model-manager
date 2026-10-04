"""
X-WIDE 插件分析管理 —— 页面数据（启动体检 / 工作流分析 / 模型分析 / 加载记录）
=====================================================================

`collector.py` 管"插件分析"那一页（谁贵、谁能动、动了谁会坏）。本文件补上另外几页需要的数据：

- `startup_info()`  启动体检：进程启动 → GUI 就绪 的分段耗时 + 每个包的两张耗时表；
- `workflows_detail()`  工作流分析：每个工作流用了哪些插件、多久没动过、缺哪些节点；
- `models_info()`  模型分析：转发给同目录的 `modelscan.py`（只读）；
- `load_records()`  模型加载记录（`__init__.py` 里装的钩子写出来的 jsonl）。

两条重要设计：

1. **不再 HTTP 回环请求自己**。`analyzer.load_object_info()` 原来是 `urlopen(http://127.0.0.1:8188/object_info)`，
   而它是在 ComfyUI 的事件循环里被调用的 —— 请求会卡住自己，8 秒超时，然后退回旧快照。
   这里改成直接读**运行中进程**的 `nodes.NODE_CLASS_MAPPINGS`（更准、即时），拿不到才退回老办法。
2. **什么都只读**。本文件不改 ComfyUI 里的任何文件，只在插件自己目录里写快照/记录。
"""

import json
import os
import re
import time

try:                      # 作为包的一部分被导入
    from . import analyzer as A
except ImportError:       # 单独跑测试时
    import analyzer as A

try:
    from . import collector as C
except ImportError:
    import collector as C

try:                      # 作为包的一部分被导入
    from . import xwide_env as E
except ImportError:       # 单独跑测试时
    import xwide_env as E

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_DIR = os.path.basename(HERE)
# 路径一律从 xwide_env 推导；加载记录写在数据目录（必须和 __init__.py 指向同一个文件）
MODELS_DIR = E.models_dir()
MODEL_LOADS = E.data_path("_model_loads.jsonl")
MODEL_LOADS_KEEP = 20000

TS_RX = re.compile(r"^\[(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.(\d+))?\]")


# ------------------------------------------------------------------ 实时节点清单

def local_object_info():
    """运行中实例的节点清单：{节点类型: {"python_module": "custom_nodes.<文件夹>..."}}。

    等价于 HTTP `/object_info` 里我们真正要用的那一个字段（节点 → 它来自哪个包），
    但不需要网络、不需要等事件循环。拿不到就抛异常，由调用方退回老办法。
    """
    import nodes as _nodes                      # ComfyUI 自己的模块；本文件只在进程内被调用
    mapping = getattr(_nodes, "NODE_CLASS_MAPPINGS", None) or {}
    if not mapping:
        raise RuntimeError("NODE_CLASS_MAPPINGS 为空")
    out = {}
    for name, cls in mapping.items():
        mod = (getattr(cls, "RELATIVE_PYTHON_MODULE", None)
               or getattr(cls, "__module__", "") or "")
        out[str(name)] = {"python_module": str(mod)}
    return out


_analyzer_load_object_info = A.load_object_info


def _cache_types():
    """现有快照里有多少个节点类型（读不出来算 0）。"""
    try:
        with open(A.OBJ_CACHE, encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        return len(d) if isinstance(d, dict) else 0
    except Exception:
        return 0


def _write_snapshot(obj):
    """写节点快照，但**绝不把好快照写小**。

    踩过的坑：在 ComfyUI 进程之外（探针脚本、别的工具）导入本插件时，
    nodes.NODE_CLASS_MAPPINGS 里只有内置的几十个节点；照写就会把已经抓好的
    六千多个节点类型的快照覆盖成几十个，于是「哪个包提供了哪些节点、
    谁用了它」全部算错（自动处理会据此误判成“没人用它”）。
    """
    try:
        n_new, n_old = len(obj or {}), _cache_types()
        if n_old and n_new < n_old:
            return False
        tmp = A.OBJ_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, A.OBJ_CACHE)
        return True
    except OSError:
        return False


def load_object_info_fast():
    """优先实时注册表；本进程注册表明显不完整时用磁盘快照；都不行退回 analyzer 的老实现。

    踩过的坑（两个方向都要防）：
      * 在 ComfyUI 进程之外（探针脚本、别的工具）导入本插件时，注册表里只有内置的
        几十个节点；这时候用它会得出「没有任何工作流用到这个包」，自动处理就会误禁。
      * 反过来，真的 ComfyUI 进程里使用者禁用了若干节点包，节点数会合理地变少，
        这时必须以**本进程**的注册表为准（磁盘快照只是上次的）。
    区分办法：真实进程至少会加载几百个节点类型，只有内置节点时是几十个。
    """
    try:
        obj = local_object_info()
    except Exception:
        return _analyzer_load_object_info()
    n_new, n_old = len(obj), _cache_types()
    if n_old and n_new < n_old:
        if n_new >= _LOCAL_TYPES_MIN:
            # 真实进程：以本进程为准，但不要写小快照（留给外部分析工具用）
            return obj, "运行中实例的实时节点注册表（%d 个类型）" % n_new, True
        try:
            with open(A.OBJ_CACHE, encoding="utf-8", errors="replace") as f:
                disk = json.load(f)
            if isinstance(disk, dict) and len(disk) >= n_old:
                return disk, ("磁盘快照（本进程只加载了 %d 个节点类型，"
                              "不够判断谁用了它）" % n_new), True
        except Exception:
            pass
        return obj, "本进程的实时节点注册表（不完整：%d 个类型）" % n_new, True
    _write_snapshot(obj)                        # 体积很小，只有“节点 → 模块”
    return obj, "运行中实例的实时节点注册表（nodes.NODE_CLASS_MAPPINGS）", True


# 低于这个数就认为「这不是一个真正加载完自定义节点的 ComfyUI 进程」
_LOCAL_TYPES_MIN = 500


# 全局生效：collector / analyzer 的所有路径都会用到这一份
A.load_object_info = load_object_info_fast


# ------------------------------------------------------------------ 进程启动时间

def process_start_time():
    """本进程的启动时间（epoch 秒）。Windows / macOS / Linux 都能用；失败返回 None。

    实现见 xwide_env.process_start_time()：psutil → Windows kernel32 → Linux /proc。
    自己写 kernel32 的老版本在非 Windows 上会直接返回 None（启动体检会缺一段）。
    """
    try:
        return E.process_start_time()
    except Exception:
        return None


# ------------------------------------------------------------------ 日志时间线

def _ts_epoch(m):
    frac = float("0." + m.group(7)) if m.group(7) else 0.0
    t = time.strptime("%s-%s-%s %s:%s:%s" % m.groups()[:6], "%Y-%m-%d %H:%M:%S")
    return time.mktime(t) + frac


def _log_lines():
    try:
        with open(A.LOG, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def log_timeline():
    """当前这份日志里，这一轮启动的几个关键时刻（epoch 秒）。"""
    out = {"file": A.LOG, "exists": os.path.exists(A.LOG), "first_ts": None,
           "prestartup_at": None, "import_at": None, "server_at": None, "gui_at": None,
           "mtime": None}
    if out["exists"]:
        try:
            out["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                         time.localtime(os.path.getmtime(A.LOG)))
        except OSError:
            pass
    lines = _log_lines()
    pending = None                              # 表头行没有时间戳，取它下一行的时间
    for ln in lines:
        m = TS_RX.match(ln)
        ts = _ts_epoch(m) if m else None
        if ts is not None and out["first_ts"] is None:
            out["first_ts"] = ts
        if "Prestartup times for custom nodes:" in ln:
            pending = "prestartup_at"
            continue
        if "Import times for custom nodes:" in ln:
            pending = "import_at"
            continue
        if pending and ts is not None:
            out[pending] = ts                  # 同一份日志里出现多次时，后面的覆盖前面的（= 最后一次启动）
            pending = None
        if ts is not None and "Starting server" in ln:
            out["server_at"] = ts
        if ts is not None and "To see the GUI go to" in ln:
            out["gui_at"] = ts
    return out


SEGMENTS = (
    ("bootstrap", "引导启动（进程启动 → 第一条日志）", "Launch (process start -> first log line)"),
    ("prestartup", "启动前脚本", "Prestartup scripts"),
    ("import", "节点导入", "Node imports"),
    ("tail", "收尾（到界面就绪）", "Finishing (until GUI ready)"),
)


def startup_info():
    """启动体检：分段耗时 + 每个包的耗时表 + 降级/失败行。"""
    t0 = time.time()
    errors = []
    log = {}
    try:
        log = A.parse_log()
    except Exception as e:
        errors.append("parse_log: %s: %s" % (type(e).__name__, e))
        log = dict(C.EMPTY_LOG)
    tl = log_timeline()
    proc = process_start_time()

    def seg(a, b):
        return round(b - a, 1) if (a and b and b >= a) else None

    secs = {
        "bootstrap": seg(proc, tl["first_ts"]),
        "prestartup": seg(tl["first_ts"], tl["prestartup_at"]),
        "import": seg(tl["prestartup_at"], tl["import_at"]),
        "tail": seg(tl["import_at"], tl["gui_at"]),
    }
    total = seg(proc, tl["gui_at"])
    if total is None:                            # 拿不到进程启动时间时，至少给出日志范围内的时间
        total = seg(tl["first_ts"], tl["gui_at"])

    segments = [{"key": k, "label_zh": zh, "label_en": en, "seconds": secs.get(k)}
                for k, zh, en in SEGMENTS]
    segments.append({"key": "total", "label_zh": "合计（进程启动 → 界面就绪）",
                     "label_en": "Total (process start -> GUI ready)", "seconds": total})

    # 每个包的两张表：prestartup / import（failed 单列）
    rows = []
    for name, s in (log.get("prestartup") or {}).items():
        rows.append({"name": name, "phase": "prestartup", "seconds": round(s, 1), "failed": False})
    for name, s in (log.get("imports") or {}).items():
        rows.append({"name": name, "phase": "import", "seconds": round(s, 1), "failed": False})
    for name, s in (log.get("failed") or {}).items():
        rows.append({"name": name, "phase": "import", "seconds": round(s, 1), "failed": True})
    rows.sort(key=lambda r: (-r["seconds"], r["name"].lower()))

    by_pack = {}
    for r in rows:
        it = by_pack.setdefault(r["name"], {"name": r["name"], "seconds": 0.0,
                                            "phases": [], "failed": False})
        it["seconds"] = round(it["seconds"] + r["seconds"], 1)
        if r["phase"] not in it["phases"]:
            it["phases"].append(r["phase"])
        it["failed"] = it["failed"] or r["failed"]
    merged = sorted(by_pack.values(), key=lambda x: (-x["seconds"], x["name"].lower()))

    notes = []
    if proc is None:
        notes.append("拿不到进程启动时间，合计只能从日志第一条算起（会少算系统引导那一段）。")
    if tl["gui_at"] and log.get("gui_ready"):
        notes.append("数据来自当前这份日志（%s），只统计最后一次启动。" % tl.get("mtime"))
    if log.get("degrade"):
        notes.append("日志里有 %d 行降级/缺失提示，见下方列表 —— 这类包不会报 IMPORT FAILED，"
                     "但功能可能少了一部分。" % len(log["degrade"]))
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 2),
        "errors": errors,
        "segments": segments,
        "total": total,
        "by_pack": merged,
        "rows": rows,
        "failed": sorted((log.get("failed") or {}).keys()),
        "degrade": (log.get("degrade") or [])[:40],
        "log": {"file": tl["file"], "exists": tl["exists"], "mtime": tl["mtime"],
                "started": log.get("started"), "gui_ready": log.get("gui_ready"),
                "server_at": log.get("server_at"),
                "first_ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(tl["first_ts"]))
                           if tl.get("first_ts") else None,
                "process_start": time.strftime("%H:%M:%S", time.localtime(proc)) if proc else None},
        "totals": {"prestartup": round(sum((log.get("prestartup") or {}).values()), 1),
                   "imports": round(sum((log.get("imports") or {}).values()), 1)},
        "notes": notes,
    }


# ------------------------------------------------------------------ 工作流分析

# /object_info 里只有**后端**注册的节点。不少包的核心节点是在 web/*.js 里用
# LiteGraph.registerNodeType(...) 注册的（例如 Goohaitools 的「孤海注释」），
# 这些永远不在 /object_info 里。判“缺节点”之前先在前端 JS 里找一遍，避免误报。
_JS_HIT = {}
_JS_SCAN = {"files": 0, "seconds": 0.0}


def _js_node_evidence(names, packs):
    """在**已启用**包的 web/js 目录里搜这些节点名（进程内缓存，只查没查过的）。"""
    want = [n for n in names if n and n not in _JS_HIT]
    if not want:
        return
    t0 = time.time()
    exts = (".js", ".mjs", ".cjs")
    skip = set(A.SKIP_DIRS) | {"node_modules", ".git", "__pycache__", "site-packages",
                               "venv", ".venv", "dist", "build"}
    hits = {n: [] for n in want}
    nfiles = 0
    stop = False
    for base, p, en in packs:
        if stop or not en or not isinstance(p, str) or not os.path.isdir(p):
            continue
        for sub in ("web", "js", "javascript", "frontend", "static"):
            root0 = os.path.join(p, sub)
            if stop or not os.path.isdir(root0):
                continue
            for root, dirs, files in os.walk(root0):
                dirs[:] = [d for d in dirs if d not in skip]
                for fn in files:
                    if not fn.lower().endswith(exts):
                        continue
                    fp = os.path.join(root, fn)
                    try:
                        if os.path.getsize(fp) > 4 * 1024 * 1024:
                            continue
                        txt = open(fp, encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    nfiles += 1
                    for n in want:
                        if len(hits[n]) < 5 and n in txt:
                            hits[n].append(os.path.relpath(fp, p))
                    if nfiles >= 3000:
                        stop = True
                        break
                if stop:
                    break
    for n in want:
        _JS_HIT[n] = hits[n]
    _JS_SCAN["files"] += nfiles
    _JS_SCAN["seconds"] = round(_JS_SCAN["seconds"] + (time.time() - t0), 2)


def _wf_files():
    out = []
    if not os.path.isdir(A.WF_DIR):
        return out
    for root, dirs, files in os.walk(A.WF_DIR):
        dirs[:] = [d for d in dirs if d not in A.SKIP_DIRS]
        for fn in files:
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(root, fn)
            try:
                if os.path.getsize(fp) > A.MAX_FILE:
                    continue
                st = os.stat(fp)
            except OSError:
                continue
            out.append({"name": fn, "path": fp, "size": st.st_size, "mtime": st.st_mtime,
                        "atime": st.st_atime})
    return out


def workflows_detail(limit=400):
    """每个工作流：用了哪些插件、多久没动、缺哪些节点。"""
    t0 = time.time()
    errors = []
    try:
        packs = [p for p in A.list_packs() if p[0] != SELF_DIR]
    except Exception as e:
        packs, errors = [], errors + ["list_packs: %s: %s" % (type(e).__name__, e)]
    enabled_of = {b: bool(en) for b, _p, en in packs}
    try:
        desc_of = A.pack_descriptions()
    except Exception as e:
        desc_of, errors = {}, errors + ["pack_descriptions: %s: %s" % (type(e).__name__, e)]
    try:
        obj, obj_src, fresh = A.load_object_info()
    except Exception as e:
        obj, obj_src, fresh = None, "不可用", False
        errors.append("object_info: %s: %s" % (type(e).__name__, e))
    try:
        n2p = A.node_to_packs(obj) if obj else {}
    except Exception as e:
        n2p, errors = {}, errors + ["node_to_packs: %s: %s" % (type(e).__name__, e)]

    node2packs = {}
    for base, nodes in (n2p or {}).items():
        for t in nodes:
            node2packs.setdefault(t, set()).add(base)

    now = time.time()
    rows, pack_wfs, type_wfs = [], {}, {}
    for f in _wf_files():
        try:
            txt = open(f["path"], encoding="utf-8-sig", errors="replace").read()
        except OSError:
            continue
        types = set()
        try:
            data = json.loads(txt)
            sub_ids, sub_nodes, body = A._split_subgraphs(data)
            A._collect_node_types(body, types)
            for nd in sub_nodes:
                A._collect_node_types(nd, types)
            types -= sub_ids
        except Exception:
            types = set(A.TYPE_RX.findall(txt))
        types -= A.VIRTUAL_TYPES
        types = {t for t in types if t not in A.DATA_TYPES and not A.UUID_RX.match(t)}
        used = set()
        for t in types:
            used.update(node2packs.get(t, ()))
            type_wfs.setdefault(t, []).append(f["name"])
        for b in used:
            pack_wfs.setdefault(b, set()).add(f["name"])
        missing = sorted(t for t in types if obj is not None and t not in obj)
        missing_js = []
        if missing:
            try:
                _js_node_evidence(missing, packs)
            except Exception as e:
                errors.append("js_node_evidence: %s: %s" % (type(e).__name__, e))
            missing_js = [t for t in missing if _JS_HIT.get(t)]
            missing = [t for t in missing if not _JS_HIT.get(t)]
        age_days = round((now - f["mtime"]) / 86400.0, 1)
        rows.append({
            "name": f["name"], "path": f["path"], "size": f["size"],
            "size_h": "%.1f MB" % (f["size"] / 1048576.0) if f["size"] >= 1048576 else "%d KB" % max(1, f["size"] // 1024),
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(f["mtime"])),
            "mt": round(f["mtime"], 1),
            "atime": time.strftime("%Y-%m-%d %H:%M", time.localtime(f["atime"])),
            "age_days": age_days,
            "types": sorted(types)[:60], "type_count": len(types),
            "packs": sorted(used), "packs_total": len(used),
            "packs_disabled": sorted(b for b in used if not enabled_of.get(b, True)),
            "missing": missing[:20], "missing_total": len(missing),
            "missing_js": missing_js[:20], "missing_js_total": len(missing_js),
            "missing_js_files": {t: _JS_HIT.get(t, [])[:3] for t in missing_js[:5]},
        })
    rows.sort(key=lambda r: -r["mt"])

    buckets = {"d7": 0, "d30": 0, "d90": 0, "older": 0}
    for r in rows:
        a = r["age_days"]
        if a <= 7:
            buckets["d7"] += 1
        elif a <= 30:
            buckets["d30"] += 1
        elif a <= 90:
            buckets["d90"] += 1
        else:
            buckets["older"] += 1

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 2),
        "errors": errors,
        "dir": A.WF_DIR,
        "count": len(rows),
        "buckets": buckets,
        "manifest": {"source": obj_src, "fresh": bool(fresh), "js_scan": dict(_JS_SCAN)},
        "items": rows[:int(limit)],
        "pack_desc": desc_of,
        "pack_wfs": [{"name": b, "workflows": sorted(w), "count": len(w),
                      "enabled": enabled_of.get(b, True), "desc": desc_of.get(b, "")}
                     for b, w in sorted(pack_wfs.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))],
        "notes": ["“最后改动”是文件时间；“最后读取”来自 Windows 访问时间，杀毒/备份扫描也会刷新它，"
                  "只能当参考。没注册的节点 = 快照里没有的类型，可能是你禁用过某个包，也可能是它本来就没装。",
                  "只在前端 JS（各包的 web/js 目录）里注册的节点不会进 /object_info —— 这类单独算“前端节点”，"
                  "不算缺失；剩下的才是真缺。"],
    }


# ------------------------------------------------------------------ 模型

def models_info(force=False):
    """转发给 modelscan.py（只读扫描）。没装/报错都不会影响别的页面。"""
    try:
        try:
            from . import modelscan as M
        except ImportError:
            import modelscan as M
        data = M.scan(force=bool(force))
        data["ok"] = True
        return data
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "hint": "缺少或损坏 modelscan.py 时，这一页会空着，其它页不受影响。"}


# ------------------------------------------------------------------ 模型加载记录

def load_records(limit=200):
    """钩子写出来的加载记录（最新在后）。"""
    if not os.path.exists(MODEL_LOADS):
        return {"ok": True, "file": MODEL_LOADS, "exists": False, "count": 0, "items": []}
    try:
        with open(MODEL_LOADS, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        return {"ok": False, "error": str(e), "file": MODEL_LOADS, "exists": True,
                "count": 0, "items": []}
    out = []
    for ln in lines[-int(limit):]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return {"ok": True, "file": MODEL_LOADS, "exists": True, "count": len(lines),
            "items": out, "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                                 time.localtime(os.path.getmtime(MODEL_LOADS)))}


def trim_load_records(keep=MODEL_LOADS_KEEP):
    """记录文件长到 keep 行以上时，只保留最后 keep 行。"""
    try:
        with open(MODEL_LOADS, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        if len(lines) <= keep:
            return 0
        with open(MODEL_LOADS + ".tmp", "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-keep:]) + "\n")
        os.replace(MODEL_LOADS + ".tmp", MODEL_LOADS)
        return len(lines) - keep
    except OSError:
        return 0
