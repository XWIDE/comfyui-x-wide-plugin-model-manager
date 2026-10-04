"""
X-WIDE 插件分析管理 —— 数据层
=====================================================================

`analyzer.py` 是从只读顾问脚本 1:1 复制过来的分析逻辑（扫 194 个包的源码/文档、
扫 45 个工作流、解析日志、解析 /object_info）。本文件只做三件事：

1. 把缓存路径指到本插件目录（插件要自包含，不依赖任何外部工作区）；
2. 把分析结果整理成可以直接 `json.dumps` 的字典给前端；
3. 内存 TTL 缓存 —— 全量扫描要一两分钟，不能让网页每刷新一次就重扫。

**只读**：本文件不写插件数据目录之外的任何地方，只写自己目录下的两个缓存文件。
真正会改文件系统的只有 `manager.py`（禁用/恢复），且每次只动一个目录。
"""

import os
import threading
import time

try:                      # 作为包的一部分被导入
    from . import analyzer as A
except ImportError:       # 单独跑测试时
    import analyzer as A

VERSION = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_DIR = os.path.basename(HERE)
# ---- 分析器的缓存/输出目录：由 xwide_env.data_dir() 决定（默认就是本插件目录）----
# analyzer 导入时已经指向数据目录；这里再钉一次，防止被外部改过 WORKSPACE。
A.WORKSPACE = A.E.data_dir()
A.REPORT = os.path.join(A.WORKSPACE, "CustomNode插件顾问报告.md")
A.OBJ_CACHE = os.path.join(A.WORKSPACE, "_object_info.json")
A.CACHE = os.path.join(A.WORKSPACE, "_pack_advisor_cache.json")
# 本插件自己不是被分析的“包”：不算依赖边，也不要因为改插件源码就作废依赖缓存
A.SKIP_DIRS = set(A.SKIP_DIRS) | {SELF_DIR}
# analyzer 里所有代码路径（build_report / cmd_check / main）都走 list_packs，
# 这里统一包一层，把本插件自己排除掉——否则它会被写进报告，还会让依赖缓存的
# needles 指纹变化、白白触发一次 2 分钟的全量重扫。
_analyzer_list_packs = A.list_packs


def _list_packs_without_self():
    return [p for p in _analyzer_list_packs() if p[0] != SELF_DIR]


A.list_packs = _list_packs_without_self

EMPTY_LOG = {"file": A.LOG, "mtime": "", "started": None, "gui_ready": None, "server_at": None,
             "prestartup": {}, "imports": {}, "failed": []}

_lock = threading.Lock()
_mem = {"at": 0.0, "data": None}


def _safe(fn, default, label, errors):
    try:
        return fn()
    except Exception as e:                     # 单个环节失败不该让整个面板白屏
        errors.append("%s: %s: %s" % (label, type(e).__name__, e))
        return default


def _collect():
    t0 = time.time()
    errors = []
    packs = [p for p in _safe(A.list_packs, [], "list_packs", errors) if p[0] != SELF_DIR]
    log = _safe(A.parse_log, dict(EMPTY_LOG), "parse_log", errors)
    obj, obj_src, fresh = _safe(A.load_object_info, (None, "不可用", False), "object_info", errors)
    n2p = _safe(lambda: A.node_to_packs(obj), {}, "node_to_packs", errors)
    _pu, type_use, nwf = _safe(A.scan_workflows, ({}, {}, 0), "scan_workflows", errors)
    edges, _norm2base, blob = _safe(lambda: A.build_edges(packs), ({}, {}, {}), "build_edges", errors)
    broad = (blob or {}).get("broad", {})
    unknown_hits = _safe(lambda: A.locate_types_in_disabled(set(demo_only_guess(type_use, obj)), packs),
                         {}, "locate_types_in_disabled", errors)
    snap_mt, newer = _safe(A.snapshot_staleness, (None, []), "snapshot_staleness", errors)

    enabled_of = {base: bool(en) for base, _p, en in packs}

    # node_to_packs 给的是 base -> {节点类型}，反查一份 节点类型 -> {base}
    node2packs = {}
    for base, nodes in (n2p or {}).items():
        for t in nodes:
            node2packs.setdefault(t, set()).add(base)

    # 工作流用量：某个包提供的节点类型，出现在哪些工作流里
    pack_wf = {}
    for t, wfs in type_use.items():
        for base in node2packs.get(t, ()):
            pack_wf.setdefault(base, set()).update(wfs)

    # 节点数：这个包在运行中的实例里注册了多少个节点类型
    nodes_of = {base: len(nodes) for base, nodes in (n2p or {}).items()}

    # 入边：谁引用了它。只把【启用中】的引用方列为“警告”，禁用中的只作参考。
    refs_on, refs_off = {}, {}
    for dep, lst in (edges or {}).items():
        for e in lst:
            tgt = refs_on if enabled_of.get(e["dependent"]) else refs_off
            tgt.setdefault(dep, []).append(e)

    def _refs(d, base, cap):
        lst = d.get(base, [])
        out = []
        seen = set()
        for e in sorted(lst, key=lambda x: x.get("kind", "")):
            key = (e["dependent"], e.get("kind"), e.get("file"), e.get("line"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"from": e["dependent"], "kind": e.get("kind", ""), "file": e.get("file", ""),
                        "line": e.get("line", 0), "text": (e.get("text") or "")[:300]})
            if len(out) >= cap:
                break
        return out, len(lst)

    unknown_of = {}
    for t, hs in (unknown_hits or {}).items():
        for (b, f, ln) in hs:
            unknown_of.setdefault(b, []).append({"type": t, "file": f, "line": ln})

    try:
        desc_of = A.pack_descriptions()
    except Exception as e:
        desc_of, errors = {}, errors + ["pack_descriptions: %s: %s" % (type(e).__name__, e)]

    items = []
    for base, path, en in packs:
        cost, det = A.cost_of(base, log)
        wfs = sorted(pack_wf.get(base, ()))
        r_on, n_on = _refs(refs_on, base, 40)
        r_off, n_off = _refs(refs_off, base, 10)
        items.append({
            "name": base,
            "path": path,
            "dir": os.path.basename(path),
            "enabled": bool(en),
            "desc": desc_of.get(base, ""),
            "cost": round(cost, 2),
            "cost_text": ("%s s" % A.fmt_secs(cost)) if cost > 0 else "-",
            "detail": det,
            "nodes": nodes_of.get(base, 0),
            "workflows": wfs[:6],
            "workflows_total": len(wfs),
            "refs": r_on, "refs_total": n_on,
            "refs_disabled": r_off, "refs_disabled_total": n_off,
            "broad": broad.get(base),
            "keep_never": base in getattr(A, "KEEP_NEVER", set()),
            "note": getattr(A, "NOTES", {}).get(base),
            "unknown": unknown_of.get(base, [])[:20],
            "raw": ((blob or {}).get("packs") or {}).get(base),
        })
    items.sort(key=lambda x: (-x["cost"], x["name"].lower()))

    cands = [i["name"] for i in items
             if i["enabled"] and i["cost"] >= A.COST_MIN and i["workflows_total"] == 0]
    risky_disabled = [i for i in items if not i["enabled"] and (i["refs_total"] or i["unknown"]
                                                               or i["workflows_total"])]
    orphans = sorted(set(demo_only_guess(type_use, obj)) - set(unknown_hits or {}))

    return {
        "version": VERSION,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 1),
        "deps_seconds": round((blob or {}).get("seconds", 0) or 0, 1),
        "deps_cache": dict((blob or {}).get("cache_info") or {}),
        "errors": errors,
        "log": {"file": log.get("file"), "mtime": log.get("mtime", ""),
                "started": log.get("started"), "gui_ready": log.get("gui_ready")},
        "manifest": {"source": obj_src, "fresh": bool(fresh),
                     "snapshot": snap_mt and time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap_mt)),
                     "newer": list(newer)[:20], "newer_total": len(newer)},
        "workflow_dir": A.WF_DIR,
        "workflows": nwf,
        "counts": {"packs": len(packs),
                   "enabled": sum(1 for _b, _p, e in packs if e),
                   "disabled": sum(1 for _b, _p, e in packs if not e)},
        "thresholds": {"cost_min": A.COST_MIN, "broad_refs": A.BROAD_REFS},
        "totals": {"prestartup": round(sum((log.get("prestartup") or {}).values()), 1),
                   "imports": round(sum((log.get("imports") or {}).values()), 1),
                   "failed": sorted(log.get("failed") or [])},
        "candidates": cands,
        "risky_disabled": [i["name"] for i in risky_disabled],
        "packs": items,
        "orphans": [{"type": t, "workflows": sorted(set(type_use.get(t, ())))[:3]} for t in orphans],
        "folded": [{"name": k, "packs": v.get("packs", 0), "refs": v.get("refs", 0),
                    "top": v.get("top", [])}
                   for k, v in sorted((broad or {}).items(), key=lambda kv: -kv[1].get("packs", 0))],
    }


def demo_only_guess(type_use, obj):
    """工作流里出现、但运行中的节点清单里没有的类型。"""
    return [t for t in type_use if t not in (obj or {})]


def collect(ttl=300.0, force=False):
    """分析结果；ttl 秒内直接返回内存里的上一份。"""
    if not force:
        data = _mem["data"]
        if data is not None and (time.time() - _mem["at"]) < ttl:
            return data
    with _lock:
        if not force:
            data = _mem["data"]
            if data is not None and (time.time() - _mem["at"]) < ttl:
                return data
        data = _collect()
        _mem["at"] = time.time()
        _mem["data"] = data
        return data


def invalidate():
    """目录被改过（禁用/恢复）之后，丢掉内存里的分析结果。"""
    with _lock:
        _mem["data"] = None
        _mem["at"] = 0.0


def cache_info():
    return {"at": _mem["at"], "age": (time.time() - _mem["at"]) if _mem["at"] else None,
            "cached": _mem["data"] is not None,
            "deps_cache_file": os.path.exists(A.CACHE),
            "deps": dict(getattr(A, "CACHE_STATUS", {}) or {}),
            "manifest_file": os.path.exists(A.OBJ_CACHE)}
