"""
X-WIDE 插件分析管理 —— 禁用 / 恢复
=====================================================================

只有一种做法：把 `custom_nodes\\<包名>` 改名成 `custom_nodes\\<包名>.disabled`（或改回来）。
这是 ComfyUI 自己认的约定（`folder_paths` / `nodes.py` 都会过滤掉 `.disabled`），
**不删任何文件、不动 python 依赖库、不动模型**，改回名字就恢复。

护栏（每条都对应之前踩过的坑）：
- 只操作 `NODES_DIR` 的**直接子目录**，且解析后的真实路径必须仍在 `NODES_DIR` 下（防路径穿越/符号链接）；
- 目标已存在就拒绝（绝不做覆盖式改名）；
- 不能操作本插件自己；
- 每次只改一个目录，动作写进 `actions.log`（谁、什么时候、从什么改成什么），可追溯；
- 返回里带 `needs_restart: True` —— 改名要重启 ComfyUI 才生效。
"""

import json
import os
import re
import time

try:                                    # 作为包的一部分被导入
    from . import xwide_env as E
except ImportError:                     # 被当脚本单独跑
    import xwide_env as E

NODES_DIR = E.custom_nodes_dir()
SELF_NAME = "X-WIDE_plugin_model_manager"
HERE = os.path.dirname(os.path.abspath(__file__))
# 动作日志跟着数据目录走（插件目录只读时会落到 <user>/X-WIDE_plugin_model_manager）
ACTION_LOG = E.data_path("actions.log")
KEEP_LINES = 400
NAME_RX = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\- ]{0,120}\Z")


def _base_of(name):
    name = (name or "").strip()
    return name[:-len(".disabled")] if name.endswith(".disabled") else name


def _is_self(path):
    """这个路径是不是本插件自己。

    只比目录名是不够的：用 ComfyUI-Manager 或 git clone 装的时候目录名可能
    是 comfyui-x-wide-plugin-model-manager 之类，护栏会失效、把自己禁掉。
    所以先按真实路径比，再退回目录名。
    """
    try:
        if os.path.realpath(path) == os.path.realpath(HERE):
            return True
    except Exception:
        pass
    return os.path.basename(os.path.normpath(_base_of(path))) == SELF_NAME


def _guard(path):
    """path 必须是 NODES_DIR 的直接子目录（解析符号链接之后再比）。"""
    real = os.path.realpath(path)
    root = os.path.realpath(NODES_DIR)
    if os.path.dirname(real) != root:
        raise ValueError("只允许操作 %s 的直接子目录：%s" % (NODES_DIR, real))
    return real


def plan(action, name):
    """算出 (src, dst) 并做全部检查，不改任何东西（dry-run 也走这里）。"""
    base = _base_of(name)
    if not NAME_RX.match(base):
        raise ValueError("包名不合法：%r" % name)
    if _is_self(os.path.join(NODES_DIR, base)):
        raise ValueError("不能操作本插件自己（%s）" % base)
    if not os.path.isdir(NODES_DIR):
        raise ValueError("找不到 %s" % NODES_DIR)
    live = _guard(os.path.join(NODES_DIR, base))
    dead = _guard(os.path.join(NODES_DIR, base + ".disabled"))
    if action == "disable":
        if not os.path.isdir(live):
            raise ValueError("没找到启用中的目录 %s（可能已经禁用了？）" % base)
        if os.path.exists(dead):
            raise ValueError("已存在 %s.disabled，请先手动处理，本插件不覆盖" % base)
        return live, dead
    if action == "enable":
        if not os.path.isdir(dead):
            raise ValueError("没找到已禁用的目录 %s.disabled" % base)
        if os.path.exists(live):
            raise ValueError("已存在 %s，请先手动处理，本插件不覆盖" % base)
        return dead, live
    raise ValueError("未知动作：%r（只支持 disable / enable）" % action)


def _write_log(entry):
    try:
        with open(ACTION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        lines = open(ACTION_LOG, encoding="utf-8", errors="replace").read().splitlines()
        if len(lines) > KEEP_LINES:
            with open(ACTION_LOG, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-KEEP_LINES:]) + "\n")
    except OSError:
        pass


def do_action(action, name, ack="", dry_run=False):
    """执行一次改名。dry_run=True 时只做检查 + 写日志，不动文件系统。"""
    t0 = time.time()
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action,
             "name": _base_of(name), "dry_run": bool(dry_run), "ack": (ack or "")[:200]}
    try:
        src, dst = plan(action, name)
    except ValueError as e:
        entry.update({"ok": False, "message": str(e), "seconds": 0})
        _write_log(entry)
        return entry
    entry["from"] = os.path.basename(src)
    entry["to"] = os.path.basename(dst)
    if dry_run:
        entry.update({"ok": True, "message": "只是检查，没有改动：%s → %s"
                      % (entry["from"], entry["to"]), "seconds": round(time.time() - t0, 2)})
        _write_log(entry)
        return entry
    try:
        os.rename(src, dst)
    except OSError as e:
        entry.update({"ok": False, "message": "改名失败：%s" % e, "seconds": round(time.time() - t0, 2)})
        _write_log(entry)
        return entry
    verb = "已禁用" if action == "disable" else "已恢复"
    entry.update({"ok": True, "needs_restart": True,
                  "message": "%s %s（重启 ComfyUI 后生效）" % (verb, entry["name"]),
                  "seconds": round(time.time() - t0, 2)})
    _write_log(entry)
    return entry


def read_log(limit=80):
    try:
        lines = open(ACTION_LOG, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-int(limit):]:
        try:
            out.append(json.loads(ln))
        except Exception:
            out.append({"raw": ln})
    return out


# ---------------------------------------------------------------- 批量

MAX_BATCH = 60


def plan_many(action, names):
    """批量预检：逐个走 plan()，一个都不改。返回 [{name, ok, from, to} | {name, ok, message}]。"""
    out = []
    for nm in names or []:
        base = _base_of(nm)
        try:
            src, dst = plan(action, nm)
            out.append({"name": base, "ok": True,
                        "from": os.path.basename(src), "to": os.path.basename(dst)})
        except ValueError as e:
            out.append({"name": base, "ok": False, "message": str(e)})
    return out


def do_actions(action, names, ack="", dry_run=False, stop_on_error=False):
    """批量改名。

    用户明确要求“插件可以批量禁用，但必须告知风险”，所以：
    - 一个都不预检通过就整体不动（plan_many 先跑一遍，全绿才动，除非 stop_on_error=False 且用户已确认）；
    - 每个包仍然各写一条 actions.log，最后再加一条批量汇总；
    - 返回里把成功/失败逐条列清楚，前端按条展示。
    """
    seq = []
    for n in (names or []):
        b = _base_of(str(n).strip())
        if b and b not in seq:
            seq.append(b)
    if not seq:
        return {"ok": False, "action": action, "total": 0, "done": 0, "failed": 0,
                "results": [], "message": "没有选中任何插件"}
    if len(seq) > MAX_BATCH:
        return {"ok": False, "action": action, "total": len(seq), "done": 0, "failed": 0,
                "results": [], "message": "一次最多 %d 个（你选了 %d 个），分批来更稳" % (MAX_BATCH, len(seq))}

    pre = plan_many(action, seq)
    blocked = [p for p in pre if not p["ok"]]
    if blocked and not stop_on_error and not dry_run:
        # 预检有问题的先摆出来，让使用者看清再决定（避免“按了一下，一半成功一半没动”）
        return {"ok": False, "action": action, "total": len(seq), "done": 0,
                "failed": len(blocked), "results": pre, "precheck": True,
                "message": "预检没通过：%d 个不能动（见列表）。确认后可以“跳过这些继续”，"
                           "或先取消它们。" % len(blocked)}

    results, done = [], 0
    t0 = time.time()
    for nm in seq:
        one = do_action(action, nm, ack=ack, dry_run=dry_run)
        results.append(one)
        if one.get("ok"):
            done += 1
        elif stop_on_error:
            break
    failed = len(results) - done
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": True, "action": action,
             "total": len(seq), "done": done, "failed": failed, "dry_run": bool(dry_run),
             "names": seq, "seconds": round(time.time() - t0, 2), "ack": (ack or "")[:200],
             "ok": done > 0 and failed == 0}
    _write_log(entry)
    verb = "禁用" if action == "disable" else "恢复"
    return {"ok": done > 0, "action": action, "total": len(seq), "done": done, "failed": failed,
            "needs_restart": bool(done and not dry_run), "results": results,
            "seconds": round(time.time() - t0, 2),
            "message": "%s %d 个，失败 %d 个（重启 ComfyUI 后生效）" % (verb, done, failed)
            if not dry_run else "只是检查，没有改动：%d 个可执行，%d 个不行" % (done, failed)}
