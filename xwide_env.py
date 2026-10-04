#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X-WIDE_plugin_model_manager —— 环境适配层（跨机器 / 跨平台 / 跨 ComfyUI 版本）

这个文件是**唯一**允许出现“路径从哪来”这个问题答案的地方。其它模块一律
`from . import xwide_env as E`，不再自己拼绝对路径。

四级推导（先问 ComfyUI 自己，问不到才猜，最后才用固定位置）：

1. `folder_paths`（ComfyUI 自带的路径模块）—— 最准；
2. 按本插件位置往上推 —— 本插件在 `<ComfyUI根>/custom_nodes/<自己>`，
   `custom_nodes` / `<根>/models` / `<根>/user` 都能算出来；
3. 环境变量覆盖（给特殊布局 / 测试用）：
   `XWIDE_COMFY_ROOT` `XWIDE_NODES_DIR` `XWIDE_MODELS_DIR` `XWIDE_USER_DIR`
   `XWIDE_WORKFLOWS_DIR` `XWIDE_LOG_FILE` `XWIDE_DATA_DIR` `XWIDE_SERVER`
4. 平台常规位置（例如 Linux 上的 `~/.local/share/ComfyUI`）—— 仅作为兜底。

数据文件（缓存 / actions.log / 模型加载记录）默认写在插件自己目录里；
插件目录只读时（某些打包安装）自动退到 `<user>/X-WIDE_plugin_model_manager/`，
所以别人机器上即使 `custom_nodes` 是只读挂载也能用。

本文件不 import 同目录其它模块（要能被单独执行/单独导入），只依赖标准库。
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_DIR = os.path.basename(HERE)
IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
_PLATFORM = "Windows" if IS_WINDOWS else ("macOS" if IS_MACOS else ("Linux" if IS_LINUX else sys.platform))

_SOURCES = {}                             # 每个路径“是怎么定出来的”，给 /ping 和界面看


# ------------------------------------------------------------------ 小工具

def _clean(p):
    if not p:
        return None
    try:
        return os.path.abspath(os.path.expanduser(str(p).strip().strip('"')))
    except Exception:
        return None


def _env(name):
    v = os.environ.get(name)
    if v is None:
        return None
    v = v.strip().strip('"').strip()
    return v or None


def _isdir(p):
    try:
        return bool(p) and os.path.isdir(p)
    except OSError:
        return False


def _isfile(p):
    try:
        return bool(p) and os.path.isfile(p)
    except OSError:
        return False


def norm_key(path):
    """比较路径用：Windows 上大小写不敏感。"""
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except Exception:
        return os.path.normcase(str(path))


def is_under(path, root):
    """path 是否在 root 里（含 root 本身）；两边都做 realpath + 大小写归一。"""
    p, r = norm_key(path), norm_key(root)
    if not p or not r:
        return False
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def safe_print(*args, **kw):
    """打印中文到控制台时，某些环境（Linux 的 ASCII locale）会抛 UnicodeEncodeError。

    插件在 import 期打印一行就崩，会让整个自定义节点加载失败——所以这里必须吞。
    """
    try:
        print(*args, **kw)
    except Exception:
        try:
            sys.stdout.write(" ".join(str(a) for a in args) + "\n")
        except Exception:
            pass


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json_atomic(path, obj):
    """先写临时文件再替换：断电/并发也不会留下半截 json。"""
    d = os.path.dirname(path) or "."
    try:
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ folder_paths

def folder_paths():
    """ComfyUI 自己的路径模块；单独跑脚本 / 单测时为 None。"""
    try:
        import folder_paths as fp          # noqa: PLC0415 - 故意延迟导入
        return fp
    except Exception:
        return None


def _fp_str(fp, *names):
    for n in names:
        v = getattr(fp, n, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _fp_paths(fp, kind):
    """folder_paths.get_folder_paths(kind) —— 顺带把相对路径补成绝对。"""
    try:
        return [p for p in (fp.get_folder_paths(kind) or []) if p]
    except Exception:
        return []


# ------------------------------------------------------------------ 各条路径

def comfy_root():
    """ComfyUI 根目录（含 main.py / custom_nodes 的那一层）。"""
    if "root" in _SOURCES:
        return _SOURCES["root"]
    v = _env("XWIDE_COMFY_ROOT")
    src = "env:XWIDE_COMFY_ROOT"
    if not v:
        v = _fp_str(folder_paths() or object(), "base_path")
        src = "folder_paths.base_path"
    if not _isdir(v):
        v = os.path.dirname(os.path.dirname(HERE))       # custom_nodes/<自己> 往上两层
        src = "按插件位置推断"
    if not _isdir(v):
        v = os.getcwd()
        src = "当前工作目录"
    out = _clean(v)
    _SOURCES["root"] = out
    _SOURCES["root_src"] = src
    return out


def custom_nodes_dir():
    """`custom_nodes` 目录（本插件的父目录）。"""
    if "nodes" in _SOURCES:
        return _SOURCES["nodes"]
    parent = _clean(os.path.dirname(HERE))
    v = _env("XWIDE_NODES_DIR")
    src = "env:XWIDE_NODES_DIR"
    if v:
        out = _clean(v)
        _SOURCES["nodes"], _SOURCES["nodes_src"] = out, src
        return out
    fp = folder_paths()
    cands = _fp_paths(fp, "custom_nodes") if fp else []
    # 有多个 custom_nodes 时，选“装着本插件”的那一个
    for d in cands:
        if norm_key(d) == norm_key(parent):
            v, src = d, "folder_paths(custom_nodes)"
            break
    if not v and cands:
        v, src = cands[0], "folder_paths(custom_nodes)[0]"
    if not _isdir(v):
        v, src = parent, "按插件位置推断"
    out = _clean(v)
    _SOURCES["nodes"] = out
    _SOURCES["nodes_src"] = src
    return out


def models_dir():
    """`models` 目录（模型页 / 模型加载记录用）。"""
    if "models" in _SOURCES:
        return _SOURCES["models"]
    v = _env("XWIDE_MODELS_DIR")
    src = "env:XWIDE_MODELS_DIR"
    if v:                                 # 环境变量是“明确指定”，直接采信（哪怕目录暂时不存在）
        out = _clean(v)
        _SOURCES["models"], _SOURCES["models_src"] = out, src
        return out
    if True:
        fp = folder_paths()
        v = _fp_str(fp, "models_dir") if fp else None
        src = "folder_paths.models_dir"
        if not v and fp:
            # 老版本没有 models_dir：从 checkpoints 那一层往上找
            for kind in ("checkpoints", "diffusion_models", "unet", "loras"):
                for d in _fp_paths(fp, kind):
                    up = _clean(os.path.dirname(_clean(d)))
                    if up and os.path.basename(up).lower() == "models":
                        v, src = up, "folder_paths(%s) 推断" % kind
                        break
                    if up:
                        v, src = up, "folder_paths(%s) 推断" % kind
                        break
                if v:
                    break
    if not _isdir(v):
        v, src = os.path.join(comfy_root(), "models"), "按 ComfyUI 根目录推断"
    out = _clean(v)
    _SOURCES["models"] = out
    _SOURCES["models_src"] = src
    return out


def user_dir():
    """ComfyUI 的 `user` 目录（日志、工作流、设置都在里面）。"""
    if "user" in _SOURCES:
        return _SOURCES["user"]
    v = _env("XWIDE_USER_DIR")
    src = "env:XWIDE_USER_DIR"
    if v:
        out = _clean(v)
        _SOURCES["user"], _SOURCES["user_src"] = out, src
        return out
    fp = folder_paths()
    f = getattr(fp, "get_user_directory", None)
    if callable(f):
        try:
            v, src = f(), "folder_paths.get_user_directory()"
        except Exception:
            v = None
    if not v:
        v = _fp_str(fp, "user_directory", "user_dir")
        src = "folder_paths.user_directory"
    if not _isdir(v):
        v, src = os.path.join(comfy_root(), "user"), "按 ComfyUI 根目录推断"
    out = _clean(v)
    _SOURCES["user"] = out
    _SOURCES["user_src"] = src
    return out


def workflows_dir():
    """工作流 json 所在目录。新版本 ComfyUI 也允许用 folder_paths 注册。"""
    if "wf" in _SOURCES:
        return _SOURCES["wf"]
    v = _env("XWIDE_WORKFLOWS_DIR")
    src = "env:XWIDE_WORKFLOWS_DIR"
    if v:
        out = _clean(v)
        _SOURCES["wf"], _SOURCES["wf_src"] = out, src
        return out
    fp = folder_paths()
    for d in _fp_paths(fp, "workflows"):
        if _isdir(d):
            v, src = d, "folder_paths(workflows)"
            break
    if not _isdir(v):
        u = user_dir()
        cands = [os.path.join(u, "default", "workflows"), os.path.join(u, "workflows"),
                 os.path.join(comfy_root(), "workflows")]
        v = next((c for c in cands if _isdir(c)), cands[0])
        src = "user 目录推断"
    out = _clean(v)
    _SOURCES["wf"] = out
    _SOURCES["wf_src"] = src
    return out


LOG_CANDIDATES = ("comfyui.log", "comfy.log")
LOG_SUBDIRS = ("", "logs")


def log_file():
    """启动日志。ComfyUI 默认写 `<user>/comfyui.log`，不同启动器可能放在别处，
    所以这里把几个常见位置都看一遍，取**最新修改**的那一个。"""
    if "log" in _SOURCES:
        return _SOURCES["log"]
    v = _env("XWIDE_LOG_FILE")
    src = "env:XWIDE_LOG_FILE"
    if not v:
        roots = [user_dir(), comfy_root()]
        cands = []
        for r in roots:
            for sub in LOG_SUBDIRS:
                for nm in LOG_CANDIDATES:
                    cands.append(os.path.join(r, sub, nm) if sub else os.path.join(r, nm))
        best = None
        for c in cands:
            if _isfile(c):
                try:
                    mt = os.path.getmtime(c)
                except OSError:
                    mt = 0.0
                if best is None or mt > best[1]:
                    best = (c, mt)
        if best:
            v, src = best[0], "自动找到"
        else:
            v, src = cands[0], "默认位置（文件还不存在）"
    out = _clean(v)
    _SOURCES["log"] = out
    _SOURCES["log_src"] = src
    return out


def server_url():
    """本机 ComfyUI 的 HTTP 地址（只在“读不到内存快照”时当兜底用）。"""
    v = _env("XWIDE_SERVER")
    if v:
        _SOURCES["server_src"] = "env:XWIDE_SERVER"
        return v.rstrip("/")
    host, port, src = None, None, "默认 127.0.0.1:8188"
    try:
        from server import PromptServer                    # noqa: PLC0415
        inst = getattr(PromptServer, "instance", None)
        p = getattr(inst, "port", None)
        if isinstance(p, int) and p > 0:
            port, src = p, "运行中的 PromptServer"
        a = getattr(inst, "address", None)
        if isinstance(a, str) and a and a not in ("0.0.0.0", "::"):
            host = a
    except Exception:
        pass
    try:
        from comfy.cli_args import args as _args          # noqa: PLC0415
        if not port:
            p = getattr(_args, "port", None)
            if isinstance(p, int) and p > 0:
                port, src = p, "启动参数 --port"
        a = getattr(_args, "listen", None)
        if isinstance(a, str) and a and a not in ("0.0.0.0", "::") and not host:
            host = a
    except Exception:
        pass
    _SOURCES["server_src"] = src
    return "http://%s:%d" % (host or "127.0.0.1", int(port or 8188))


# ------------------------------------------------------------------ 数据目录

_DATA_DIR = None


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".xwide_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


def data_dir():
    """本插件写文件的地方（缓存 / actions.log / 模型加载记录）。

    优先插件自己目录（自包含、好找）；只读时退到 `<user>/<插件名>`；
    再不行退到系统临时目录。结果缓存，不会每次调用都写盘测试。
    """
    global _DATA_DIR
    if _DATA_DIR:
        return _DATA_DIR
    v = _env("XWIDE_DATA_DIR")
    if v:
        d = _clean(v)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        if _isdir(d):
            _SOURCES["data_src"] = "env:XWIDE_DATA_DIR"
            _DATA_DIR = d
            return d
    if _writable(HERE):
        _SOURCES["data_src"] = "插件自己目录"
        _DATA_DIR = HERE
        return HERE
    alt = os.path.join(user_dir(), SELF_DIR)
    if _writable(alt):
        _SOURCES["data_src"] = "ComfyUI user 目录（插件目录只读）"
        _DATA_DIR = alt
        return alt
    tmp = os.path.join(tempfile.gettempdir(), SELF_DIR)
    _writable(tmp)
    _SOURCES["data_src"] = "系统临时目录（前两处都不可写）"
    _DATA_DIR = tmp
    return tmp


def data_path(*parts):
    return os.path.join(data_dir(), *parts)


# ------------------------------------------------------------------ 平台相关行为

def filetime_to_unix(ticks):
    """Windows FILETIME(100ns, 1601 起) → unix 秒。"""
    return ticks / 1e7 - 11644473600.0


def process_start_time():
    """本进程的启动时间（epoch 秒）；拿不到就返回 None。

    Windows 用 kernel32；Linux 读 /proc；装了 psutil 的话优先用 psutil（最省事、最准）。
    上层已经能处理 None（退回“日志第一条时间”），所以这里失败不算错。
    """
    try:
        import psutil                                      # noqa: PLC0415
        return float(psutil.Process().create_time())
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            import ctypes
            import ctypes.wintypes as wt
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x0400, False, os.getpid())     # PROCESS_QUERY_INFORMATION
            if not h:
                return None
            created, exited, kern, usr = (wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME())
            ok = k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                     ctypes.byref(kern), ctypes.byref(usr))
            k32.CloseHandle(h)
            if not ok:
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return filetime_to_unix(ticks)
        except Exception:
            return None
    if IS_LINUX:
        try:
            with open("/proc/self/stat", encoding="utf-8", errors="replace") as f:
                rest = f.read().split(") ", 1)[1].split()
            starttime = float(rest[19])                    # 第 22 个字段（去掉 pid 与 comm）
            hz = float(os.sysconf("SC_CLK_TCK"))
            btime = None
            with open("/proc/stat", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    if ln.startswith("btime "):
                        btime = float(ln.split()[1])
                        break
            if btime is None:
                return None
            return btime + starttime / hz
        except Exception:
            return None
    return None                                            # macOS 且没有 psutil：交给上层退回日志时间


def open_in_file_manager(path):
    """在系统文件管理器里打开目录 / 定位文件。返回一句说明（给界面显示）。"""
    p = _clean(path)
    if not p or not os.path.exists(p):
        raise FileNotFoundError("路径不存在：%s" % p)
    isdir = os.path.isdir(p)
    if IS_WINDOWS:
        if isdir:
            os.startfile(p)                                # noqa: S606 - 本地工具，路径已校验
            return "explorer"
        # explorer /select 只认反斜杠路径，且必须拼成 /select,<path>
        subprocess.Popen(["explorer", "/select," + os.path.normpath(p)])   # noqa: S603
        return "explorer /select"
    if IS_MACOS:
        cmd = ["open", p] if isdir else ["open", "-R", p]
        subprocess.Popen(cmd)                              # noqa: S603
        return "open" + ("" if isdir else " -R")
    target = p if isdir else (os.path.dirname(p) or ".")
    for cmd in (["xdg-open", target], ["gio", "open", target], ["nautilus", target]):
        try:
            subprocess.Popen(cmd)                          # noqa: S603
            return cmd[0]
        except FileNotFoundError:
            continue
        except Exception:
            continue
    raise RuntimeError("找不到可用的文件管理器命令（xdg-open / gio / nautilus）")


# ------------------------------------------------------------------ 自述

def platform_label():
    return _PLATFORM


def python_version():
    return "%d.%d.%d" % sys.version_info[:3]


def describe():
    """给 /ping 用：这些路径是怎么定出来的 + 关键开关，方便别人机器上排查。"""
    fp = folder_paths()
    out = {
        "platform": _PLATFORM,
        "python": python_version(),
        "plugin_dir": HERE,
        "plugin_folder": SELF_DIR,
        "folder_paths": fp is not None,
        "data_dir": data_dir(),
        "data_dir_src": _SOURCES.get("data_src", "?"),
        "paths": {},
        "env": {},
    }
    for key, fn, src_key in (("comfy_root", comfy_root, "root_src"),
                             ("custom_nodes", custom_nodes_dir, "nodes_src"),
                             ("models", models_dir, "models_src"),
                             ("user", user_dir, "user_src"),
                             ("workflows", workflows_dir, "wf_src"),
                             ("log", log_file, "log_src"),
                             ("server", server_url, "server_src")):
        try:
            out["paths"][key] = fn()
        except Exception as e:
            out["paths"][key] = "?（%s: %s）" % (type(e).__name__, e)
        out["paths"][key + "_src"] = _SOURCES.get(src_key, "?")
    for name in ("XWIDE_COMFY_ROOT", "XWIDE_NODES_DIR", "XWIDE_MODELS_DIR", "XWIDE_USER_DIR",
                 "XWIDE_WORKFLOWS_DIR", "XWIDE_LOG_FILE", "XWIDE_DATA_DIR", "XWIDE_SERVER",
                 "XWIDE_MODEL_LOGS"):
        v = _env(name)
        if v:
            out["env"][name] = v
    return out


def check():
    """自检：每个路径存不存在、能不能写。界面/命令行都能用。"""
    d = describe()
    exists = {}
    for k in ("comfy_root", "custom_nodes", "models", "user", "workflows"):
        exists[k] = _isdir(d["paths"].get(k))
    exists["log"] = _isfile(d["paths"].get("log"))
    d["exists"] = exists
    d["writable"] = {"data_dir": _writable(d["data_dir"])}
    d["seconds"] = None
    return d


if __name__ == "__main__":                                  # 单独跑：python xwide_env.py
    t0 = time.time()
    info = check()
    info["seconds"] = round(time.time() - t0, 2)
    print(json.dumps(info, ensure_ascii=False, indent=2))
