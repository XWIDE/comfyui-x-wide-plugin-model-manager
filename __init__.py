"""
X-WIDE_plugin_model_manager
=====================================================================

一个纯本地、只读优先的 ComfyUI 自定义节点管理器：

- **分析**：扫 `custom_nodes` 下每个包的源码/文档依赖、扫你的工作流用到了哪些节点、
  解析启动日志里每个包的耗时，最后给出「谁贵、谁你能动、动了谁会坏」。
- **依赖警告**：禁用某个包之前，先告诉你**启用中的包**里有谁引用了它（带 `文件:行号` 原始证据），
  以及你的工作流是不是真的用到了它的节点。
- **管理**：改名 `custom_nodes\\<包>` ↔ `<包>.disabled`（ComfyUI 自己的约定），
  不删文件、不动 pip 包、**绝不动模型**；每次动作写进 `actions.log`，改回名字就恢复。
- **模型加载记录**（可选，`XWIDE_MODEL_LOGS=0` 可关）：给 `comfy.storage.annotate_state_dict`
  加一层只记录、不拦截的包装 —— 从此以后"哪个模型真的被加载过"有据可查。
  它只往插件自己目录的 `_model_loads.jsonl` 追加一行，失败也绝不会影响模型加载。

界面在左侧边栏的一个新页签里（`web/xwide_plugin_manager.js`），共 5 页：
启动体检 / 插件分析 / 工作流分析 / 模型分析 / 动作记录。

后端只暴露本地 API：

    GET  /xwide/plugin-manager/ping
    GET  /xwide/plugin-manager/analyze?force=0        插件分析（缓存 5 分钟）
    GET  /xwide/plugin-manager/startup                启动体检
    GET  /xwide/plugin-manager/workflows              工作流分析
    GET  /xwide/plugin-manager/models?force=0         模型分析（只读）
    GET  /xwide/plugin-manager/loads?limit=200        模型加载记录
    GET  /xwide/plugin-manager/hooks                  加载钩子状态
    POST /xwide/plugin-manager/action                 {action, name|names, ack, dry_run, stop_on_error}
    POST /xwide/plugin-manager/open                   {path} 在资源管理器里定位（只允许白名单目录）
    GET  /xwide/plugin-manager/log?limit=80
    GET  /xwide/plugin-manager/report                 返回已生成的报告文本
    POST /xwide/plugin-manager/report                 重新生成报告文件（较慢）

本插件不联网、不装包、不改 ComfyUI 自身的任何文件。
"""

import asyncio
import json
import os
import subprocess
import time
import traceback

from aiohttp import web

from . import autopilot, collector, manager

# 这些模块出问题也不该让整个自定义节点加载失败
try:
    from . import pages
except Exception as _e:                                    # pragma: no cover
    pages = None
    print("[X-WIDE_plugin_model_manager] pages 模块未加载：%s: %s" % (type(_e).__name__, _e))

__version__ = "1.1.0"
WEB_DIRECTORY = "./web"

# ComfyUI 认这两个映射（本插件不加节点，给空字典即可）
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]

LOG_PREFIX = "[X-WIDE_plugin_model_manager]"
PREFIX = "/xwide/plugin-manager"
HERE = os.path.dirname(os.path.abspath(__file__))

try:                                    # 路径解析的唯一出口（跨平台 / 跨机器 / 可被环境变量覆盖）
    from . import xwide_env as E
except ImportError:                     # pragma: no cover
    import xwide_env as E

# 拿不到 PromptServer 实例时不要抛出——那会让整个自定义节点加载失败。
# 用一个空的装饰器把注册语句变成“什么都不做”，插件代码仍然可用（只是没有 API）。
try:
    from server import PromptServer
    _REAL_ROUTES = PromptServer.instance.routes
except Exception as e:                      # pragma: no cover
    _REAL_ROUTES = None
    print("%s 无法注册 API 路由（%s: %s），界面会拿不到数据。" % (LOG_PREFIX, type(e).__name__, e))


class _NoRoutes:
    def get(self, *_a, **_k):
        return lambda f: f

    def post(self, *_a, **_k):
        return lambda f: f


routes = _REAL_ROUTES if _REAL_ROUTES is not None else _NoRoutes()


def _json(payload, status=200):
    try:
        return web.json_response(payload, status=status)
    except Exception:                        # 极端情况下回退成字符串
        return web.Response(text=str(payload), status=status)


def _need_pages():
    if pages is None:
        raise RuntimeError("pages 模块没加载成功，这一页暂时不可用")


def _truthy(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ================================================================ 模型加载记录钩子

MODEL_LOADS = E.data_path("_model_loads.jsonl")
_HOOK = {"installed": False, "records": 0, "last": None, "since": None, "reason": "",
         "switch": "XWIDE_MODEL_LOGS=0 可关闭"}
_OFF = ("0", "false", "no", "off", "disable", "disabled")


def _record_load(path):
    """往 _model_loads.jsonl 追加一行。任何异常都不许往外冒。"""
    try:
        p = os.path.realpath(str(path))
        rel = p
        try:
            base = os.path.realpath(pages.MODELS_DIR) if pages else None
            if base and p.lower().startswith(base.lower() + os.sep):
                rel = os.path.relpath(p, base)
        except Exception:
            pass
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "rel": rel, "path": p}
        with open(MODEL_LOADS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _HOOK["records"] += 1
        _HOOK["last"] = rec["time"]
        if _HOOK["records"] % 200 == 0 and pages is not None:
            pages.trim_load_records()
    except Exception:
        pass


def install_model_load_hook():
    """只记录、不拦截：模型文件被真正读进来时写一行日志。

    挂载点选 `comfy.storage.annotate_state_dict` —— `comfy.utils.load_torch_file()`
    在读完文件后必定调用它（`comfy/utils.py:204`，模块属性查找，所以在运行时替换有效），
    拿到的 `path` 就是模型真实路径。
    """
    if os.environ.get("XWIDE_MODEL_LOGS", "").strip().lower() in _OFF:
        _HOOK["reason"] = "已按 XWIDE_MODEL_LOGS 关闭"
        return
    try:
        import comfy.storage as _storage
    except Exception as e:
        _HOOK["reason"] = "拿不到 comfy.storage：%s: %s" % (type(e).__name__, e)
        return
    orig = getattr(_storage, "annotate_state_dict", None)
    if not callable(orig):
        _HOOK["reason"] = "comfy.storage.annotate_state_dict 不存在（ComfyUI 版本变了？）"
        return
    if getattr(orig, "_xwide_wrapped", False):
        _HOOK["installed"] = True
        _HOOK["reason"] = "已经装过了"
        return

    def _wrapped(state_dict, path):
        out = orig(state_dict, path)          # 先让它干正事，绝不影响加载
        try:
            _record_load(path)
        except Exception:
            pass
        return out

    _wrapped._xwide_wrapped = True
    try:
        _storage.annotate_state_dict = _wrapped
    except Exception as e:
        _HOOK["reason"] = "替换失败：%s: %s" % (type(e).__name__, e)
        return
    _HOOK["installed"] = True
    _HOOK["since"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _HOOK["reason"] = "只在 load_torch_file 这条路径上记录"


try:
    install_model_load_hook()
except Exception as _e:                                    # pragma: no cover
    _HOOK["reason"] = "%s: %s" % (type(_e).__name__, _e)


# ================================================================ API

@routes.get(PREFIX + "/ping")
async def _ping(request):
    return _json({"ok": True, "name": "X-WIDE_plugin_model_manager", "version": __version__,
                  "folder": os.path.basename(HERE),
                  "nodes_dir": manager.NODES_DIR, "nodes_dir_exists": os.path.isdir(manager.NODES_DIR),
                  "pages": pages is not None, "model_hook": _HOOK["installed"]})


@routes.get(PREFIX + "/analyze")
async def _analyze(request):
    q = request.rel_url.query
    force = _truthy(q.get("force"))
    try:
        ttl = float(q.get("ttl") or 300)
    except ValueError:
        ttl = 300.0
    try:
        # 重活放到线程里：冷扫要一两分钟，不能占着事件循环（那会把 ComfyUI 界面卡住）
        data = await asyncio.to_thread(collector.collect, ttl, force)
        return _json({"ok": True, "data": data})
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/startup")
async def _startup(request):
    try:
        _need_pages()
        return _json({"ok": True, "data": await asyncio.to_thread(pages.startup_info)})
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/workflows")
async def _workflows(request):
    try:
        _need_pages()
        return _json({"ok": True, "data": await asyncio.to_thread(pages.workflows_detail)})
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/models")
async def _models(request):
    try:
        _need_pages()
        force = _truthy(request.rel_url.query.get("force"))
        data = await asyncio.to_thread(pages.models_info, force)
        # modelscan 只知道「记录文件在不在」，钩子到底装没装只有这里知道 —— 合并成一份真实状态
        try:
            lh = data.setdefault("load_hook", {})
            lh["installed"] = bool(_HOOK["installed"])
            lh["since"] = _HOOK.get("since")
            lh["reason"] = _HOOK.get("reason")
            lh["switch"] = _HOOK.get("switch")
            lh["file"] = _HOOK.get("file") or lh.get("file")
            lh["records"] = max(int(lh.get("records") or 0), int(_HOOK.get("records") or 0))
            lh["last"] = lh.get("last") or _HOOK.get("last")
            lh["hook_running"] = True
        except Exception:
            pass
        return _json({"ok": True, "data": data})
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/loads")
async def _loads(request):
    try:
        _need_pages()
        limit = int(request.rel_url.query.get("limit") or 200)
    except Exception:
        limit = 200
    try:
        return _json({"ok": True, "data": pages.load_records(limit)})
    except Exception as e:
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/hooks")
async def _hooks(request):
    return _json({"ok": True, "hook": dict(_HOOK), "file": MODEL_LOADS,
                  "file_exists": os.path.exists(MODEL_LOADS)})


@routes.get(PREFIX + "/cache")
async def _cache(request):
    return _json({"ok": True, "cache": collector.cache_info()})


@routes.post(PREFIX + "/action")
async def _action(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    action = str(body.get("action", "")).strip().lower()
    name = str(body.get("name", "") or "").strip()
    names = body.get("names")
    ack = str(body.get("ack", "") or "")
    dry_run = bool(body.get("dry_run"))
    stop_on_error = bool(body.get("stop_on_error", True))
    try:
        if isinstance(names, list) and names:
            res = await asyncio.to_thread(manager.do_actions, action, names,
                                          ack=ack, dry_run=dry_run, stop_on_error=stop_on_error)
        else:
            res = await asyncio.to_thread(manager.do_action, action, name,
                                          ack=ack, dry_run=dry_run)
    except Exception as e:                    # do_action 自己会吞掉预期错误，这里是兜底
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)
    if res.get("ok") and not dry_run:
        collector.invalidate()                # 目录变了，下次必须重扫
    return _json({"ok": bool(res.get("ok")), "result": res}, status=200 if res.get("ok") else 400)


@routes.post(PREFIX + "/open")
async def _open(request):
    """在资源管理器里定位一个文件/文件夹。只允许白名单目录，绝不执行别的东西。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = os.path.realpath(str((body or {}).get("path", "")))
    roots = [os.path.realpath(manager.NODES_DIR), HERE]
    if pages is not None:
        roots += [os.path.realpath(pages.MODELS_DIR), os.path.realpath(collector.A.WF_DIR)]
    if not path or not any(os.path.normcase(path) == os.path.normcase(r)
                           or os.path.normcase(path).startswith(os.path.normcase(r) + os.sep)
                           for r in roots):
        return _json({"ok": False, "error": "只允许打开白名单目录里的路径：%s" % path}, status=400)
    if not os.path.exists(path):
        return _json({"ok": False, "error": "路径不存在：%s" % path}, status=404)
    try:
        E.open_in_file_manager(path)        # Windows: 资源管理器 / macOS: Finder / Linux: xdg-open
        return _json({"ok": True, "path": path})
    except Exception as e:
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.get(PREFIX + "/log")
async def _log(request):
    try:
        limit = int(request.rel_url.query.get("limit") or 80)
    except ValueError:
        limit = 80
    return _json({"ok": True, "log": manager.read_log(limit)})


@routes.get(PREFIX + "/report")
async def _report_get(request):
    path = collector.A.REPORT
    if not os.path.exists(path):
        return _json({"ok": False, "error": "还没有生成报告文件，先在面板上点“生成报告文件”。",
                      "path": path}, status=404)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return _json({"ok": False, "error": "读不出来：%s" % e}, status=500)
    return _json({"ok": True, "path": path, "seconds": None, "text": text,
                  "mtime": os.path.getmtime(path)})


@routes.post(PREFIX + "/report")
async def _report_post(request):
    try:
        await asyncio.to_thread(collector.collect)            # 先保证分析结果是最新的
        path, _packs, _edges, _log, _cands, _unknown = await asyncio.to_thread(collector.A.build_report)
        return _json({"ok": True, "path": path})
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


# ------------------------------------------------------------------ 自动处理
#
# 语义（和界面上的勾选一一对应）：
#   * 没勾「自动处理」= 只在打开插件页时扫一次，给建议，什么都不动；
#   * 勾上 = 扫描 + 自动禁用「从没被工作流用到」的包（可选：连很久没用的也一起）；
#   * 所有动作都走 manager，和安全手册、动作日志、一键恢复完全一致；
#   * dry_run=true 只返回计划，不做任何改动（默认就是 true）。

@routes.get(PREFIX + "/settings")
async def _settings_get(request):
    try:
        return _json({"ok": True, "data": await asyncio.to_thread(autopilot.state)})
    except Exception as e:
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.post(PREFIX + "/settings")
async def _settings_post(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    kw = {}
    if "enabled" in body:
        kw["enabled"] = _truthy(body.get("enabled"))
    if body.get("mode") in ("never_used", "never_used_or_stale"):
        kw["mode"] = body["mode"]
    if body.get("days") is not None:
        try:
            kw["days"] = max(1, min(3650, int(body["days"])))
        except (TypeError, ValueError):
            pass
    try:
        await asyncio.to_thread(lambda: autopilot.save_state(**kw))
        return _json({"ok": True, "data": await asyncio.to_thread(autopilot.state), "saved": kw})
    except Exception as e:
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)


@routes.post(PREFIX + "/auto")
async def _auto(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    dry = _truthy(body.get("dry_run"), True)
    mode = body.get("mode") if body.get("mode") in ("never_used", "never_used_or_stale") else None
    try:
        days = int(body["days"]) if body.get("days") is not None else None
    except (TypeError, ValueError):
        days = None
    try:
        res = await asyncio.to_thread(autopilot.run, dry, True, mode, days)
    except Exception as e:
        traceback.print_exc()
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)
    if res.get("applied"):
        collector.invalidate()
    return _json({"ok": bool(res.get("ok")), "result": res},
                 status=200 if res.get("ok") else 400)


@routes.post(PREFIX + "/auto/restore")
async def _auto_restore(request):
    """把自动处理禁用的包恢复启用（只认它自己禁的那批）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    names = (body or {}).get("names")
    if names is not None and not isinstance(names, list):
        names = None
    try:
        res = await asyncio.to_thread(autopilot.restore, names)
    except Exception as e:
        return _json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, status=500)
    if res.get("done"):
        collector.invalidate()
    return _json({"ok": bool(res.get("ok")), "result": res},
                 status=200 if res.get("ok") else 400)


# ------------------------------------------------------------------ 独立窗口
#
# 为什么要有这个页面：面板默认在 ComfyUI 的侧边栏里，只能在主界面里用，
# 也不能拖到第二台显示器。这个页面是同一个前端脚本的“独立外壳”：
# 它设置 __XWIDE_STANDALONE__，脚本就不去 import ComfyUI 的 app.js，
# 直接把大页面铺满整个窗口。数据仍来自正在运行的 ComfyUI（同源 fetch）。
#
# 脚本地址**不能写死**：ComfyUI 只把扩展资源挂在 /extensions/<插件目录名>/ 下面
# （nodes.py: `EXTENSION_WEB_DIRS[module_name] = web_dir`，module_name 就是目录名），
# 而目录名随安装方式变化 —— 手动解压、ComfyUI-Manager、Registry 安装的目录名都不一样。
# 所以这里优先走本插件自己的固定路由 <PREFIX>/web/<文件>，再依次回退到 /extensions/ 下的名字。

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_ASSET_JS = "xwide_plugin_manager.js"
_ASSET_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _project_name():
    """从 pyproject.toml 里读出 `[project]` 的 name。

    有些 ComfyUI 版本会用 pyproject 里的项目名去注册扩展目录，所以它也当一个候选。
    不引第三方依赖，也不用 tomllib（requires-python 是 3.10，标准库 tomllib 要 3.11）。
    """
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml"),
                  "r", encoding="utf-8") as f:
            in_project = False
            for line in f:
                s = line.strip()
                if s.startswith("["):
                    in_project = s == "[project]"
                    continue
                if in_project and s.startswith("name") and "=" in s:
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _web_js_urls():
    """按“最可能成功”的顺序给出前端脚本地址（去重、保序）。"""
    urls = [PREFIX + "/web/" + _ASSET_JS]
    try:
        folder = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
        if folder:
            urls.append("/extensions/%s/%s" % (folder, _ASSET_JS))
    except Exception:
        pass
    name = _project_name()
    if name:
        urls.append("/extensions/%s/%s" % (name, _ASSET_JS))
    out = []
    for u in urls:
        if u not in out:
            out.append(u)
    return out


UI_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X-WIDE 插件与模型管理</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #1b1b1f; color: #ddd;
               font: 13px/1.55 "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; }
  /* 页面的提示条（写哪台 ComfyUI、可以拖到第二显示器）由面板脚本自己画，见 .xpm-satip：
     面板根节点是 position:fixed;inset:0，外壳里再放一条提示会被它盖住（实测确实看不到）。 */
  #xpm-shell-body { padding: 12px; }
  #xpm-shell-body h1 { font-size: 15px; margin: 0 0 8px; }
  #xpm-shell-body code { color: #ffd479; }
</style>
</head>
<body>
<div id="xpm-shell-body"></div>
<script type="module">
  window.__XWIDE_STANDALONE__ = true;
  (async function () {
    // 依次尝试：本插件自己的固定路由 → /extensions/<插件目录名>/ → /extensions/<pyproject 项目名>/
    var tries = __XWIDE_WEB_JS_LIST__;
    var last = null;
    for (var i = 0; i < tries.length; i++) {
      try { await import(tries[i]); return; } catch (e) { last = e; }
    }
    // 注意：这里写的是外壳自己的容器 xpm-shell-body —— 面板脚本内部也有一个叫 xpm-body 的容器，
    // 两个同名 id 会让 document.getElementById 拿到错的那个，所以外壳这个必须改名。
    document.getElementById("xpm-shell-body").innerHTML =
      '<pre style="padding:14px;color:#ff9a9a;white-space:pre-wrap">'
      + "前端脚本加载失败：" + (last && last.message ? last.message : String(last))
      + "\\n\\n已经试过这几个地址：\\n" + tries.join("\\n")
      + "\\n\\n请确认插件目录里的 web/__ASSET_JS__ 还在；"
      + "或者直接用 ComfyUI 主界面侧边栏里的入口（那条路不依赖这些地址）。</pre>";
  })();
</script>
</body>
</html>
"""


def _ui_html():
    return (UI_HTML
            .replace("__XWIDE_WEB_JS_LIST__", json.dumps(_web_js_urls()))
            .replace("__ASSET_JS__", _ASSET_JS))


@routes.get(PREFIX + "/ui")
async def _ui(request):
    return web.Response(text=_ui_html(), content_type="text/html", charset="utf-8")


@routes.get(PREFIX + "/web/{name}")
async def _web_asset(request):
    """把插件自己的 web/ 静态文件也从本插件的前缀下面挂一份（只读 + 后缀白名单）。

    独立窗口靠它才能在**任何**安装目录名下都打开：ComfyUI 的 /extensions/<目录名>/
    用的是目录名，用户手动改名、Manager 安装、Registry 安装各不相同。
    """
    name = os.path.basename(request.match_info.get("name") or "")
    ext = os.path.splitext(name)[1].lower()
    path = os.path.join(_WEB_DIR, name)
    if not name or ext not in _ASSET_MIME or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Content-Type": _ASSET_MIME[ext],
                                           "Cache-Control": "no-cache"})


E.safe_print("%s v%s 已加载。左侧边栏点“插件分析管理”（5 页：启动体检/插件分析/工作流分析/模型分析/动作记录）。"
             % (LOG_PREFIX, __version__))
if not _HOOK["installed"]:
    E.safe_print("%s 模型加载记录未启用：%s" % (LOG_PREFIX, _HOOK["reason"]))
