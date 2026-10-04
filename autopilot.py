"""自动处理（autopilot）：只在**用户勾上开关**时才动手，扫一遍插件包，把
「从来没有被任何工作流用到」的包禁用掉（可选：把「很久没用」的也禁用）。

设计原则（每一条都是为了"不破坏现有功能"）：

1. **默认只算不动**。plan() 纯只读；run(dry_run=True) 也只返回计划。
2. **只做目录改名**，等同于点第 2 页的「禁用」按钮，走的是同一个 manager，
   所以动作日志、护栏、预检、恢复全都一致（没有第二套实现）。
3. **宁可不做，不可做错**。命中下面任何一条就绝不自动禁用，并给出原因：
   - 本插件自己 / ComfyUI-Manager 这类 KEEP_NEVER 的包；
   - **有别的启用中插件 import 它**（依赖边 > 0）——禁了会把别人弄坏；
   - 被大量文件引用（broad >= A.BROAD_REFS）；
   - 源码最近 3 天内改过（可能正在开发中）；
   - 已禁用（不需要再动）。
4. **一次最多动 max_disable 个**（默认 12，且不超过启用中包总数的一半），
   剩下的下次再说——批量改名要留给用户反应时间。
5. **记名**。谁被自动禁用都写进状态文件（managed 列表），第 5 页和一键恢复
   都靠它；用户手动禁用的不会被记到这里。
6. 取消勾选 = 只扫描，不执行；并且**只在打开插件页时才扫描**（前端控制），
   不在 ComfyUI 启动时扫任何东西。

状态文件：<数据目录>/autopilot.json（默认就是本插件目录，只读时退到 user 目录）。
"""

import os
import time

try:                                    # 作为包的一部分被导入
    from . import analyzer as A
    from . import collector as C
    from . import manager as M
    from . import xwide_env as E
except ImportError:                     # 被当脚本单独跑
    import analyzer as A
    import collector as C
    import manager as M
    import xwide_env as E

VERSION = "1.0.0"

STATE_FILE = E.data_path("autopilot.json")

# 默认值：勾上开关后，把「从没被工作流用到」的包禁用；
# days 只对 mode="never_used_or_stale"（把很久没用的也算上）有意义。
DEFAULTS = {
    "enabled": False,          # 用户没勾之前，一切都只是「扫描 + 建议」
    "mode": "never_used",      # never_used | never_used_or_stale
    "days": 90,                # 多久算「很久没用」
    "last_run": None,          # 上次自动处理时间
    "last": None,              # 上次的结果摘要
    "managed": [],             # 由自动处理禁用的包名（可一键恢复）
}

# 源码最近改过的包不动：可能正在开发，禁了会打断人
DEV_GUARD_DAYS = 3
MAX_DISABLE = 12


# ------------------------------------------------------------------ 状态

def load_state():
    d = dict(DEFAULTS)
    try:
        import json
        if os.path.isfile(STATE_FILE):
            raw = json.loads(open(STATE_FILE, encoding="utf-8", errors="replace").read())
            if isinstance(raw, dict):
                for k in DEFAULTS:
                    if k in raw:
                        d[k] = raw[k]
    except Exception:
        pass
    if d.get("mode") not in ("never_used", "never_used_or_stale"):
        d["mode"] = "never_used"
    try:
        d["days"] = max(1, int(d.get("days") or DEFAULTS["days"]))
    except Exception:
        d["days"] = DEFAULTS["days"]
    d["enabled"] = bool(d.get("enabled"))
    if not isinstance(d.get("managed"), list):
        d["managed"] = []
    return d


def save_state(**kw):
    d = load_state()
    d.update(kw)
    try:
        import json
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass
    return d


def state():
    """给界面用：设置 + 自动处理禁用了哪些 + 它们现在的状态。"""
    d = load_state()
    managed = []
    for name in d.get("managed") or []:
        live = os.path.isdir(os.path.join(M.NODES_DIR, name))
        dead = os.path.isdir(os.path.join(M.NODES_DIR, name + ".disabled"))
        managed.append({"name": name, "enabled": live, "disabled": dead,
                        "exists": live or dead})
    d["managed_detail"] = managed
    d["state_file"] = STATE_FILE
    d["dev_guard_days"] = DEV_GUARD_DAYS
    d["max_disable"] = MAX_DISABLE
    d["cost_min"] = A.COST_MIN
    return d


# ------------------------------------------------------------------ 判断

def _wf_mtimes():
    """工作流文件名 -> 最后修改时间。只看文件名，和 scan_workflows 的 key 对齐。"""
    out = {}
    try:
        for root, dirs, files in os.walk(A.WF_DIR):
            dirs[:] = [x for x in dirs if x not in A.SKIP_DIRS]
            for fn in files:
                if not fn.lower().endswith(".json"):
                    continue
                try:
                    out[fn] = os.path.getmtime(os.path.join(root, fn))
                except OSError:
                    pass
    except Exception:
        pass
    return out


def _pack_workflows(obj, type_use):
    """包名 -> 用到它的工作流文件名集合（节点类型 → 工作流 反查）。"""
    n2p = {}
    try:
        n2p = A.node_to_packs(obj)
    except Exception:
        n2p = {}
    out = {}
    for base, types in (n2p or {}).items():
        s = set()
        for t in types or ():
            s |= set(type_use.get(t) or ())
        out[base] = s
    return out


def _skip_reason(p, now, days, mode):
    """返回 (是否候选, 原因, 是否「受保护不能动」)。"""
    base = p.get("name") or ""
    if not p.get("enabled"):
        return False, "已经禁用了", False
    if base == M.SELF_NAME or os.path.realpath(p.get("path") or "") == os.path.realpath(E.HERE):
        return False, "本插件自己", True
    if p.get("keep_never") or base in getattr(A, "KEEP_NEVER", set()):
        return False, "受保护（KEEP_NEVER，禁了会让管理器/依赖链出问题）", True
    refs = p.get("refs") or []
    hard = [r for r in refs if (r.get("kind") or "") in ("import", "dynamic", "list")]
    if hard:
        who = sorted({(r.get("from") or "?") for r in hard})
        return False, "有 %d 个启用中的插件真的 import 了它（%s）——禁了会连累别人" % (
            len(who), "、".join(who[:3])), True
    decl = [r for r in refs if (r.get("kind") or "") == "doc-strong"]
    if decl:
        who = sorted({(r.get("from") or "?") for r in decl})
        return False, "有 %d 个插件在文档里写明依赖它（%s）——管理器/别人可能靠它" % (
            len(who), "、".join(who[:3])), True
    b = p.get("broad")
    if isinstance(b, dict) and (b.get("packs") or 0) >= getattr(A, "BROAD_REFS", 12):
        return False, "被 %d 个包的文档广泛提到（生态泛引用），影响面太大" % b["packs"], True
    if p.get("unknown"):
        return False, "工作流里有 %d 处指向它的节点类型" % len(p["unknown"]), True
    try:
        mt = A.pack_source_mtime(p.get("path") or "")
    except Exception:
        mt = 0.0
    if mt and (now - mt) / 86400.0 < DEV_GUARD_DAYS:
        return False, "源码 %d 天内改过，可能正在开发" % DEV_GUARD_DAYS, True
    if (p.get("cost") or 0) < getattr(A, "COST_MIN", 1.5):
        return False, "启动开销只有 %s 秒，省不出时间" % (p.get("cost") or 0), False
    if (p.get("workflows_total") or 0) == 0:
        return True, "没有任何工作流用到它", False
    if mode == "never_used_or_stale":
        lu = p.get("_last_used") or 0
        if lu:
            age = (now - lu) / 86400.0
            if age >= days:
                return True, "最近一次用到是 %.0f 天前" % age, False
            return False, "%.0f 天前还在用（阈值 %d 天）" % (age, days), False
        return True, "工作流里有它但找不到文件时间，按「很久没用」处理", False
    return False, "工作流还在用它（想连很久没用的也一起处理，请在页面上切换模式）", False


def plan(force=False, mode=None, days=None):
    """只读地算一遍：哪些包可以自动禁用、哪些被挡住、为什么。"""
    t0 = time.time()
    st = load_state()
    mode = mode or st["mode"]
    try:
        days = max(1, int(days if days is not None else st["days"]))
    except Exception:
        days = st["days"]
    errors = []
    try:
        data = C.collect(ttl=0.0 if force else 300.0, force=bool(force))
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "candidates": [], "blocked": [], "skipped": []}
    packs = list(data.get("packs") or [])
    obj = {}
    try:
        obj, _src, _fresh = A.load_object_info()
    except Exception as e:
        errors.append("读节点清单失败：%s: %s" % (type(e).__name__, e))
    type_use = {}
    try:
        _pu, type_use, _nwf = A.scan_workflows()
    except Exception as e:
        errors.append("扫工作流失败：%s: %s" % (type(e).__name__, e))
    wf_mt = _wf_mtimes()
    pwf = _pack_workflows(obj, type_use)
    now = time.time()

    for p in packs:
        wfs = set(pwf.get(p.get("name")) or ())
        if not wfs and p.get("workflows_total"):
            wfs = set(p.get("workflows") or ())          # 兜底：collector 的统计
        mt = [wf_mt[w] for w in wfs if w in wf_mt]
        p["_wfs"] = len(wfs)
        p["_last_used"] = max(mt) if mt else 0.0
        p["_last_used_text"] = (time.strftime("%Y-%m-%d", time.localtime(p["_last_used"]))
                                if p["_last_used"] else "")

    cands, blocked, skipped = [], [], []
    for p in packs:
        if not p.get("enabled"):
            continue
        ok, why, hard = _skip_reason(p, now, days, mode)
        row = {"name": p.get("name"), "cost": p.get("cost"), "cost_text": p.get("cost_text"),
               "nodes": p.get("nodes"), "workflows_total": p.get("workflows_total"),
               "last_used": p.get("_last_used_text"), "why": why}
        if ok:
            cands.append(row)
        elif hard:
            blocked.append(row)
        else:
            skipped.append(row)

    cands.sort(key=lambda r: (-(r.get("cost") or 0), (r.get("name") or "").lower()))
    enabled_n = sum(1 for p in packs if p.get("enabled"))
    cap = min(MAX_DISABLE, max(1, enabled_n // 2))
    over = cands[cap:]
    cands = cands[:cap]
    return {
        "ok": True,
        "mode": mode, "days": days, "thresholds": {"cost_min": A.COST_MIN,
                                                   "max_disable": cap},
        "candidates": cands, "blocked": blocked, "skipped": skipped,
        "over_cap": over,
        "counts": {"enabled": enabled_n, "candidates": len(cands),
                   "blocked": len(blocked), "skipped": len(skipped),
                   "over_cap": len(over)},
        "seconds": round(time.time() - t0, 1),
        "errors": errors,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "would_save": round(sum((c.get("cost") or 0) for c in cands), 1),
    }


def run(dry_run=True, force=True, mode=None, days=None, ack="自动处理"):
    """dry_run=True 时只算；否则按计划逐个禁用（走 manager，和手动点一样）。"""
    res = plan(force=force, mode=mode, days=days)
    if not res.get("ok"):
        return res
    names = [c["name"] for c in res["candidates"]]
    res["dry_run"] = bool(dry_run)
    res["names"] = names
    if dry_run or not names:
        res["applied"] = False
        res["results"] = []
        return res
    results, done = [], []
    for name in names:
        try:
            r = M.do_action("disable", name, ack=ack)
        except Exception as e:
            r = {"ok": False, "name": name, "message": "%s: %s" % (type(e).__name__, e)}
        results.append({"name": name, "ok": bool(r.get("ok")), "message": r.get("message") or ""})
        if r.get("ok"):
            done.append(name)
    st = load_state()
    managed = sorted(set(st.get("managed") or []) | set(done))
    save_state(managed=managed, last_run=time.strftime("%Y-%m-%d %H:%M:%S"),
               last={"done": len(done), "failed": len(results) - len(done),
                     "names": done, "mode": res.get("mode"), "days": res.get("days")})
    try:
        C.invalidate()                       # 目录变了，下次重扫
    except Exception:
        pass
    res["applied"] = bool(done)
    res["results"] = results
    res["done"] = len(done)
    res["failed"] = len(results) - len(done)
    res["managed"] = managed
    res["needs_restart"] = bool(done)
    return res


def restore(names=None, ack="自动处理(恢复)"):
    """把自动处理禁用的包恢复启用（只动 managed 列表里的）。"""
    st = load_state()
    want = [n for n in (names if names is not None else st.get("managed") or [])]
    if not want:
        # 没有任何要恢复的包：这不是错误（用户可能在没禁用过的情况下点了恢复，
        # 也可能显式传了个空名单）。ok=True 让路由回 200，前端按 done=0 显示
        # 「没有需要恢复的包」，而不会弹一个吓人的失败提示。
        return {"ok": True, "done": 0, "failed": 0, "results": [],
                "managed": sorted(set(st.get("managed") or [])),
                "needs_restart": False, "message": "没有需要恢复的包"}
    results, done = [], []
    for name in want:
        if not os.path.isdir(os.path.join(M.NODES_DIR, name + ".disabled")):
            results.append({"name": name, "ok": False, "message": "不是已禁用状态，跳过"})
            continue
        try:
            r = M.do_action("enable", name, ack=ack)
        except Exception as e:
            r = {"ok": False, "name": name, "message": "%s: %s" % (type(e).__name__, e)}
        results.append({"name": name, "ok": bool(r.get("ok")), "message": r.get("message") or ""})
        if r.get("ok"):
            done.append(name)
    managed = sorted(set(st.get("managed") or []) - set(done))
    save_state(managed=managed)
    try:
        C.invalidate()
    except Exception:
        pass
    return {"ok": bool(done), "done": len(done), "failed": len(results) - len(done),
            "results": results, "managed": managed, "needs_restart": bool(done)}
