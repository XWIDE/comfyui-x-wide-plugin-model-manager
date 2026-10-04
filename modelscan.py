# -*- coding: utf-8 -*-
"""
X-WIDE 模型分析 —— 数据层（只读清点 + 使用情况判断）
=====================================================================

回答用户唯一真正关心的问题：**这 680 GB 模型里，哪些从来没人用过？**
并且诚实地标出：哪些其实是节点包在后台自己加载的，**不能动**。

判定顺序（强 → 弱，`_probe_auto_models2.py` 的同一套规则）：

    used       工作流文件里出现了这个模型的文件名
    auto_path  源码里出现了「带目录分隔符的路径」（完整相对路径，或最末两段）
    auto_name  源码里点名了这个**具体的**文件名（够长、不是通用名）
    auto_dir   所在顶层目录是「按约定自动加载」的模型库目录（sam / sams / birefnet / ...）
    unknown    通用文件名（unet.pth / diffusion_pytorch_model.safetensors / ...）或
               diffusers 仓库式目录（<repo>\\unet\\... <repo>\\transformer\\...）→ 说不清
    nobody     以上都没有 → 真·没人提（优先看这一档）

设计约束
--------
* **只读**：只 `stat`/读文件，绝不改模型、工作流、源码，也绝不重启 ComfyUI。
  唯一会写的是本插件目录下自己的 `_modelscan_cache.json`。
* **只用标准库**：不 import torch / comfy / 第三方包，也不联网；可以直接用
  ComfyUI 自带的 python 单独跑。
* **import 时零开销**：`import modelscan` 不碰磁盘，所有工作都在 `scan()` 里做。
* **单个文件出错不牵连全局**：所有异常都收进 `errors`，`scan()` 本身不抛。

对外 API
--------
    scan(force=False) -> dict      清点结果（内存缓存 + `_modelscan_cache.json` 磁盘缓存）
    cache_info()      -> dict      缓存状态：{"at", "age", "cached", "cache_file", "cache_mtime"}
    invalidate()      -> None      丢掉内存缓存（磁盘缓存仍在）
"""

import json
import os
import re
import threading
import time

VERSION = "1.0.0"

try:                                    # 作为包的一部分被导入（ComfyUI 加载时）
    from . import xwide_env as E
except ImportError:                     # 被当脚本单独跑
    import xwide_env as E

HERE = os.path.dirname(os.path.abspath(__file__))
# 缓存与加载记录都写在数据目录（插件目录只读时自动退到 <user>/<插件名>）
CACHE_FILE = E.data_path("_modelscan_cache.json")
LOAD_HOOK_FILE = E.data_path("_model_loads.jsonl")

# 路径一律从 xwide_env 推导（folder_paths → 按插件位置推断 → XWIDE_* → 平台常规位置），
# 这样换盘符、换机器、换 ComfyUI 发行版都不用改代码。
COMFY_ROOT = E.comfy_root()
MODELS_DIR = E.models_dir()
WORKFLOW_DIR = E.workflows_dir()
SRC_ROOTS = [os.path.join(COMFY_ROOT, "comfy"), E.custom_nodes_dir()]

# 算「模型权重」的扩展名（跟只读探针一致：332 个 / 680.0 GB）
WEIGHT_EXT = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft"}
# 遍历时跳过的目录名（跟探针一致）
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".disabled"}

# 通用文件名：出现在任何 diffusers 仓库里都叫这个名字，点名它等于没点名
GENERIC_NAMES = {
    "model.safetensors", "diffusion_pytorch_model.safetensors",
    "diffusion_pytorch_model.bin", "pytorch_model.bin", "model.ckpt",
    "diffusion_model.safetensors", "unet.pth", "model.pth", "weights.pth",
    "checkpoint.pth", "model.pt",
    # 追加的一批（更保守：通用名 + 分片名，一律不算「点名」）
    "ae.sft", "unet.pt", "vae.safetensors", "vae.pt", "model.fp16.safetensors",
    "diffusion_pytorch_model.fp16.safetensors", "pytorch_model.fp16.bin",
    "weights.safetensors", "checkpoint.safetensors", "model.onnx",
}
# diffusers 仓库式目录：出现在路径里 → 「这是某个仓库的一份子，说不清」
DIFFUSERS_SUBDIRS = {"transformer", "unet_main", "text_encoder", "vae", "unet"}
# 按约定「目录里有什么就加载什么」的模型库目录
AUTOLOAD_DIRS = {
    "ultralytics", "insightface", "facexlib", "facerestore_models", "vae_approx",
    "clip_interrogator", "birefnet", "birefnet-hr", "ben", "ben2", "sams", "sam", "sam2",
    "groundingdino", "depth", "detection", "mmdets", "reactor", "segformer_face",
    "segformer_fashion", "segformer_clothes", "segformer_b2_clothes", "face_parsing",
    "openunmix", "vitmatte", "lama", "facedetection", "body_segment", "rembg",
    "dz_facedetailer", "interpolation", "onnx", "yolo", "prompt_generator", "mediapipe",
    "landmarks", "photomaker", "florence2", "llama", "deepseek", "ollama", "molmo",
}

TIER_ORDER = ["used", "auto_path", "auto_name", "auto_dir", "unknown", "nobody"]
TIER_ZH = {
    "used": "被工作流用到",
    "auto_path": "后台自动调用（源码写了完整路径）",
    "auto_name": "后台自动调用（源码点名了文件名）",
    "auto_dir": "约定目录自动加载",
    "unknown": "说不清（diffusers/通用文件名）",
    "nobody": "谁都没提（优先看）",
}
TIER_EN = {
    "used": "used by a workflow",
    "auto_path": "auto-loaded (full path in source)",
    "auto_name": "auto-loaded (filename in source)",
    "auto_dir": "auto-loaded (convention folder)",
    "unknown": "unclear (diffusers/generic name)",
    "nobody": "nobody mentions it",
}

MAX_EVIDENCE = 4        # 每个文件最多留几条源码证据
EVIDENCE_CHARS = 200    # 每行证据最多截断到多少个字符
SOURCE_MAX_BYTES = 4_000_000   # 超过这个大小的 .py 不读（探针同款保护）
SOURCE_THREADS = 16            # 读源码语料的线程数（纯 I/O 等待，多开几个划算）

# 工作流里的模型文件名「token」：从 <引号/等号/斜杠…> 后面抓一段以权重扩展名结尾的文本。
# 用途：先取「这份工作流可能提到的名字」的小集合，再拿它跟权重文件名求交集 ——
# 否则每个工作流都要跟 332 个文件名各做一次全文本查找（45 × 332 次 ≈ 太慢）。
_WORDS = re.compile(r"[^\s\"'<>:,;|*?\\/\[\]{}()]+\.(?:safetensors|ckpt|pth|pt|bin|gguf|onnx|sft)\b",
                    re.I)
# token 的边界字符，跟 `_WORDS` 里那个否定字符集是同一套
_TOKEN_STOP = frozenset(" \t\r\n\f\v\"'<>:,;|*?\\/[]{}()")
# 只锚定「以扩展名结尾」，不用贪婪前缀。`_WORDS` 那种写法遇到工作流里内嵌的 base64 大块
# （几十万字符里一个分隔符都没有）会退化成平方级回溯 —— 实测光这一步就要 15 s。
_EXT_ANCHOR = re.compile(r"\.(?:safetensors|ckpt|pth|pt|bin|gguf|onnx|sft)\b", re.I)
_TOKEN_BACK = 300          # 向前最多回看多少字符拼一个文件名（NTFS 文件名上限 255）


def _names_in(text, lower_names):
    """
    从一份工作流文本里挑出「与 lower_names 相交的文件名」，返回命中的小写名字集合。

    先线性扫出所有 `.safetensors`/`.pth` 之类的扩展名结尾，再从这里向前走到 token 边界，
    拼出候选文件名 —— 语义与 `_WORDS` 相同（token = 一串非边界字符，以已知扩展名结尾），
    但没有平方级回溯。`text` 必须已经小写。
    """
    hits = set()
    if not text:
        return hits
    for m in _EXT_ANCHOR.finditer(text):
        end = m.start()
        j = lo = end
        lo = j - _TOKEN_BACK if j > _TOKEN_BACK else 0
        while j > lo and text[j - 1] not in _TOKEN_STOP:
            j -= 1
        tok = text[j:m.end()]
        if tok in lower_names:
            hits.add(tok)
    return hits

_LOCK = threading.Lock()
_MEM = {"data": None, "at": 0.0, "seconds": None}   # 进程内缓存
_CORPUS = None                 # 进程内源码语料：{rel: text, ...}（不落盘，太占地方）
_CORPUS_MARK = None            # 语料对应的源码指纹，指纹变了就重读


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _fmt_bytes(n):
    """1234567 -> '1.2 MB'（沿用探针的 1024 进制与一位小数，保证 680.0 GB 不变）"""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit, div in (("TB", 1024.0 ** 4), ("GB", 1024.0 ** 3), ("MB", 1024.0 ** 2), ("KB", 1024.0)):
        if abs(n) >= div:
            return "%.1f %s" % (n / div, unit)
    return "%.0f B" % n


def _fmt_time(ts):
    """时间戳 -> 'YYYY-MM-DD HH:MM'；拿不到就返回 None（前端按「未知」显示）"""
    if not ts:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def _fmt_time_full(ts):
    """时间戳 -> 'YYYY-MM-DD HH:MM:SS'；拿不到返回 None"""
    if not ts:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def _safe(fn, default, label, errors):
    """单个环节失败不该让整个面板白屏（沿用 collector.py 的写法）"""
    try:
        return fn()
    except Exception as e:                     # noqa: BLE001 —— 这里就是要兜住一切
        errors.append("%s: %s: %s" % (label, type(e).__name__, e))
        return default


def _newest_mtime(paths):
    """一批文件里最新的 mtime（整秒）；一个都取不到就是 0.0"""
    newest = 0.0
    for p in paths:
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m > newest:
            newest = m
    return float(int(newest))


def _sniff_timestamp(v):
    """`_model_loads.jsonl` 的 time 字段可能是秒/毫秒时间戳，也可能是字符串，都认"""
    if isinstance(v, (int, float)):
        t = float(v)
        if t > 1e11:               # 毫秒
            t /= 1000.0
        return t
    if isinstance(v, str) and v.strip():
        s = v.strip().replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
            try:
                return time.mktime(time.strptime(s[:19], fmt))
            except ValueError:
                continue
    return 0.0


def _scan_tree(root, skip_dirs=SKIP_DIRS, ext_filter=None, want_stat=True):
    """
    用 os.scandir 递归遍历目录，返回 [(abspath, relpath, size, mtime, atime), ...]。

    Windows 上 `DirEntry.stat()` 的数据是目录枚举时顺手带回来的，不用再发一次
    CreateFile/GetFileAttributes —— 8557 + 4664 个文件走下来，比 os.walk + os.stat
    省 1 秒多。缓存命中也得把这三棵树走一遍算指纹，所以这一秒是每次调用都要付的。

    不跟软链接/联接点（和 os.walk 默认的 followlinks=False 一致，也避免目录环）。
    stat 失败的文件静默跳过：坏一个文件不该让整次扫描失败。
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        for ent in entries:
            try:
                if ent.is_dir(follow_symlinks=False):
                    if ent.name not in skip_dirs:
                        stack.append(ent.path)
                    continue
                if ext_filter is not None:
                    if os.path.splitext(ent.name)[1].lower() not in ext_filter:
                        continue
                st = ent.stat(follow_symlinks=False) if want_stat else None
            except OSError:
                continue
            out.append((ent.path, os.path.relpath(ent.path, root), st.st_size, st.st_mtime,
                        getattr(st, "st_atime", None)))
    return out


# --------------------------------------------------------------------------
# 一、磁盘清点（模型目录 / 工作流 / 源码）
# --------------------------------------------------------------------------
def _stat_models(errors):
    """走一遍 models 目录：全部文件（含非权重）+ 权重清单 + 目录指纹"""
    all_files = []
    for p, rel, size, mtime, atime in _scan_tree(MODELS_DIR):
        if rel.startswith(".."):
            errors.append("models: 越界路径，已跳过：%s" % p)
            continue
        all_files.append((rel, size, mtime, atime))
    return all_files


def _models_sig(all_files):
    """
    models 目录指纹：文件数 + 总字节 + 最新 mtime。
    故意做成「便宜」的：刻意不含每个文件的 mtime，否则同体积替换会被误判成没变。
    """
    return {
        "files": len(all_files),
        "bytes": sum(f[1] for f in all_files),
        "newest_mtime": round(max((f[2] for f in all_files), default=0.0), 0),
    }


def _stat_sources(errors):
    """走一遍 comfy/ 与 custom_nodes/，收集所有 .py 的路径与 mtime（不读内容）"""
    out = []
    for base in SRC_ROOTS:
        if not os.path.isdir(base):
            continue
        for p, rel, size, mtime, _atime in _scan_tree(base, ext_filter={".py"}):
            out.append({"rel": os.path.relpath(p, COMFY_ROOT), "abs": p,
                        "mtime": round(mtime, 3), "size": size})
    return out


def _sources_sig(meta):
    """源码指纹：文件数 + 总字节 + 最新 mtime + 每一条 (路径, mtime, 大小) 的稳定散列。

    用 zlib.crc32 而不是 sha256：8556 条记录要秒级算完，抗意外碰撞够用。
    """
    import zlib
    parts = sorted("%s|%s|%s" % (m["rel"], m["mtime"], m["size"]) for m in meta)
    blob = "\n".join(parts).encode("utf-8", "replace")
    return {
        "files": len(meta),
        "bytes": sum(m["size"] for m in meta),
        "newest_mtime": round(max((m["mtime"] for m in meta), default=0.0), 0),
        "digest": "%08x" % (zlib.crc32(blob) & 0xFFFFFFFF),
    }


def _load_corpus(meta, errors):
    """读所有源码文本（只读小文件），返回 {相对路径: 小写文本}。

    8557 个小文件、约 100 MB。这步几乎全是 I/O 等待（打开/关闭 8557 次），所以开
    `SOURCE_THREADS` 个线程轮流领活；顺序必须稳定（按相对路径排序）—— `_evidence`
    取前几条命中，顺序变了证据就变了。

    早先的写法是把文件切成 512 个一批、每批新建一批线程，光线程创建就 8700 多个，
    换成一个固定线程池之后这步从 4.4 s 降到 2 s 上下。
    """
    corpus = {}
    todo = [m for m in meta if m["size"] <= SOURCE_MAX_BYTES]
    if not todo:
        return corpus
    todo.sort(key=lambda m: m["rel"].lower())
    lock = threading.Lock()
    cursor = [0]
    n = len(todo)

    def _worker():
        while True:
            with lock:
                i = cursor[0]
                if i >= n:
                    return
                cursor[0] = i + 1
            m = todo[i]
            try:
                with open(m["abs"], encoding="utf-8", errors="ignore") as f:
                    text = f.read().lower()
            except OSError as e:
                errors.append("source_read: %s: %s" % (m["rel"], e))
                continue
            corpus[m["rel"]] = text

    threads = [threading.Thread(target=_worker, name="modelscan-read-%d" % i)
               for i in range(min(SOURCE_THREADS, n))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return corpus


def _stat_workflows(errors):
    """所有工作流 .json：[(文件名, 绝对路径, 小写文本), ...]（按路径排序，保证稳定）

    递归找：工作流是按子目录分类放的（qwen2.1/、H3/ …），只扫一层会漏掉大部分。
    """
    items = []
    if not os.path.isdir(WORKFLOW_DIR):
        errors.append("workflows: 目录不存在：%s" % WORKFLOW_DIR)
        return items
    for p, _rel, _size, _mtime, _atime in _scan_tree(WORKFLOW_DIR, ext_filter={".json"}):
        fn = os.path.basename(p)
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                items.append((fn, p, f.read().lower()))
        except OSError as e:
            errors.append("workflows: %s: %s" % (fn, e))
    items.sort(key=lambda x: x[1].lower())
    return items


# --------------------------------------------------------------------------
# 二、分类
# --------------------------------------------------------------------------
def _classify(rel, base, corpus, where, errors):
    """
    返回 (tier, evidence)。rel 是相对 models 的路径（反斜杠），base 是小写文件名。
    `where` 是「这个文件名出现在哪些源码文件里」的索引（找不到就是空列表）。
    """
    rel_bs = rel.replace("/", "\\").lower()
    rel_fw = rel_bs.replace("\\", "/")
    parts_seg = [p for p in rel_bs.split("\\") if p]
    folder = parts_seg[0] if parts_seg else ""
    # 末两段：diffusers 仓库里 basename 常常没意义，但「仓库\子目录\文件」有
    tail = "\\".join(rel_bs.split("\\")[-2:]) if len(rel_bs.split("\\")) >= 2 else ""
    tail_fw = tail.replace("\\", "/")

    # ---- auto_path：源码里写了路径（完整相对路径，或最末两段） ----
    if rel_bs in where:
        return "auto_path", _evidence(rel_bs, where, corpus, errors, "path")
    if rel_fw in where:
        return "auto_path", _evidence(rel_fw, where, corpus, errors, "path")
    if tail and tail in where:
        return "auto_path", _evidence(tail, where, corpus, errors, "tail")
    if tail_fw and tail_fw in where:
        return "auto_path", _evidence(tail_fw, where, corpus, errors, "tail")

    # ---- auto_name：源码点名了这个具体文件名 ----
    specific = (base not in GENERIC_NAMES and len(base) >= 10
                and not base.startswith("pytorch_model-")
                and not (base.startswith("model-") and base.endswith(".safetensors")))
    if specific and where.get(base):
        return "auto_name", _evidence(base, where, corpus, errors, "name")

    # ---- auto_dir：约定目录自动加载 ----
    if folder in AUTOLOAD_DIRS:
        return "auto_dir", []

    # ---- unknown：通用名 / diffusers 仓库式目录 ----
    parts = {p for p in parts_seg[:-1]}
    if base in GENERIC_NAMES or (parts & DIFFUSERS_SUBDIRS):
        return "unknown", []

    # ---- nobody ----
    return "nobody", []


def _evidence(needle, where, corpus, errors, kind):
    """把命中行抠出来：file / line / text（≤200 字符），最多 MAX_EVIDENCE 条"""
    out = []
    for rel in where.get(needle, ())[:MAX_EVIDENCE]:
        text = corpus.get(rel)
        if text is None:
            errors.append("evidence: 语料里没找到 %s" % rel)
            continue
        lower = text.lower()
        pos = lower.find(needle)
        if pos < 0:
            pos = 0
        line_no = lower.count("\n", 0, pos) + 1
        ls = lower.rfind("\n", 0, pos) + 1
        le = lower.find("\n", pos)
        if le < 0:
            le = len(lower)
        out.append({"file": rel, "line": line_no,
                    "text": text[ls:le].strip()[:EVIDENCE_CHARS], "kind": kind})
        if len(out) >= MAX_EVIDENCE:
            break
    return out


def _ext_of(needle):
    """从针里取扩展名（用来做便宜的前置过滤）；取不到就返回空串"""
    i = needle.rfind(".")
    if i < 0 or len(needle) - i > 12:
        return ""
    return needle[i:]


def _build_where(corpus, needles):
    """
    对每个针做一次「谁提到了它」的查询，返回 {针: [源码相对路径, ...]}（没人提的针不进结果）。

    语料是 8557 个源码文件、约 100 MB 文本，朴素做法是拿每个针去问每个文件
    （620 个针 × 8557 个文件，实测 15 s 量级）。这里两层过滤：

    1. 文件名针：按扩展名分组，先看这个文件里有没有出现过该扩展名（`if ext in text`，
       一次 C 级查找），没有就整组跳过。`ext` 是针的后缀，所以「针在文本里」必然推出
       「ext 在文本里」—— 这道过滤只会跳过必然不匹配的针，不会漏。一个 .py 里最多
       出现两三种权重扩展名，于是每个文件真正要做的针查找从几百次降到几次。
    2. 路径针（带分隔符的）：只有出现过「它的文件名」的文件才可能出现「它的路径」，
       所以只在第 1 步已经命中的那些文件里找。这一步把路径针的候选文件从上千个
       缩到个位数。

    实测把整体从 ~15 s 压到 1 s 上下，结果与「全量两两查找」完全一致。
    """
    where = {}
    if not needles:
        return where
    plain, paths = [], []
    for n in needles:
        (paths if ("\\" in n or "/" in n) else plain).append(n)

    by_ext = {}
    for n in plain:
        by_ext.setdefault(_ext_of(n), []).append(n)
    for rel, text in corpus.items():
        for ext, group in by_ext.items():
            if ext and ext not in text:
                continue
            for n in group:
                if n in text:
                    where.setdefault(n, []).append(rel)

    by_base = {}
    for n in paths:
        base = n.replace("/", "\\").rsplit("\\", 1)[-1]
        by_base.setdefault(base, []).append(n)
    for base, group in by_base.items():
        files = where.get(base)
        if not files:
            continue                      # 连文件名都没人提，路径更不可能有人提
        for rel in files:
            text = corpus.get(rel)
            if not text:
                continue
            for n in group:
                if n in text:
                    where.setdefault(n, []).append(rel)
    return where


# --------------------------------------------------------------------------
# 三、加载记录（另一个部件写的 _model_loads.jsonl）
# --------------------------------------------------------------------------
def _load_hook(errors):
    """
    读 `_model_loads.jsonl`（每行一个 JSON：{"time","rel","path"}）。
    只做朴素解析：解析不了的行直接跳过（不猜、不修）。
    """
    info = {"installed": False, "records": 0, "last": None, "file": LOAD_HOOK_FILE,
            "bytes": 0, "mtime": 0.0}
    try:
        st = os.stat(LOAD_HOOK_FILE)
    except OSError:
        return info, {}, {}
    info["installed"] = True
    info["bytes"] = st.st_size
    info["mtime"] = st.st_mtime
    by_rel, by_base = {}, {}
    bad = 0
    try:
        with open(LOAD_HOOK_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if not isinstance(row, dict):
                    bad += 1
                    continue
                rel = str(row.get("rel") or "").replace("/", "\\").strip()
                if not rel:
                    p = str(row.get("path") or "").replace("/", "\\").strip()
                    if p.lower().startswith(MODELS_DIR.replace("/", "\\").lower()):
                        rel = p[len(MODELS_DIR) + 1:]
                if not rel:
                    bad += 1
                    continue
                ts = _sniff_timestamp(row.get("time"))
                info["records"] += 1
                for key, table in ((rel.lower(), by_rel),
                                   (os.path.basename(rel).lower(), by_base)):
                    slot = table.setdefault(key, [0, 0.0])
                    slot[0] += 1
                    if ts > slot[1]:
                        slot[1] = ts
    except OSError as e:
        errors.append("load_hook: %s" % e)
        return info, {}, {}
    if bad:
        errors.append("load_hook: 跳过 %d 行无法解析的记录" % bad)
    info["last"] = _fmt_time_full(max((v[1] for v in by_rel.values()), default=0.0))
    return info, by_rel, by_base


# --------------------------------------------------------------------------
# 四、主流程
# --------------------------------------------------------------------------
def _notes(data_head):
    """给用户看的大白话说明 —— 每一句都必须是真的。"""
    notes = [
        "这份清单是对 ComfyUI 的**只读**扫描：没有改动、移动或删除任何模型文件，"
        "也没有重启 ComfyUI；唯一写出的是本插件目录下的 _modelscan_cache.json。",
        "「被工作流用到」= 这个模型的文件名出现在 user\\default\\workflows 下任意一个 .json 里。"
        "局限性：ComfyUI 的工作流只存名字不存路径，所以名字相同但放在不同子目录的模型会一起被算作「用到」"
        "（不会漏报，只会多算）；另外 API 方式调用、压根没存成工作流的用法，扫不出来。",
        "「后台自动调用」分四类：auto_path=某个 .py 源码里写了它的完整路径（最硬的证据，带文件名+行号）；"
        "auto_name=源码点名了这个具体文件名；auto_dir=它所在的顶层目录是「目录里有什么就加载什么」的"
        "模型库目录（例如 sam、sams、birefnet、facerestore_models、ultralytics），目录里放什么就加载什么，"
        "**这些文件删了会静默变成重新下载或直接报错**。",
        "unknown（说不清）指的是通用文件名（unet.pth / diffusion_pytorch_model.safetensors / pytorch_model.bin 等）"
        "或 diffusers 仓库式目录（<仓库>\\unet\\、<仓库>\\transformer\\、<仓库>\\vae\\ 里的分片）。"
        "名字太普通、又是某个本地仓库的一份子，**不能靠这份清单判它没用**。",
        "nobody = 工作流没提、源码没提、也不在约定目录里。这是最值得先看的一档，但**不等于可以删**："
        "它可能被改过名的副本、被动态拼出来的路径、被 ComfyUI-Manager 的模型列表、"
        "或还没存成工作流的临时实验引用到。删之前请先改名、跑一遍常用工作流再决定。",
        "最后访问时间（atime）不是「用过」的证据：Windows/NTFS 默认不更新它，"
        "而且杀毒、备份、网盘同步、资源管理器预览都会刷新它 —— 所以清单里会出现一大堆文件共享同一个 atime。"
        "只有「最近打开过」这一个用途上，它才勉强有点参考价值。",
    ]
    if data_head.get("bytes_all"):
        notes.append("体积口径：bytes_total（%s）= 只算模型权重文件；bytes_all（%s）= models 目录下全部文件 "
                     "（多出来的那部分是配置 json、txt、图片等零碎）。这两个数不一样，别当成矛盾。"
                     % (data_head.get("bytes_total_h"), data_head.get("bytes_all_h")))
    hook = data_head.get("load_hook") or {}
    if hook.get("installed"):
        notes.append("模型加载记录来自本插件目录下的 _model_loads.jsonl（%d 条）。"
                     "它是加载钩子写出来的，钩子没装上、或 ComfyUI 是用别的启动器起的，这个文件就会是空的或者不存在 —— "
                     "所以「加载次数 0」只代表**没记录**，不代表没用过。" % hook.get("records", 0))
    else:
        notes.append("没有找到 _model_loads.jsonl（模型加载钩子还没启用），所以这一列全是 0："
                     "那是「没记录」，不是「没用过」。")
    notes.append("缓存会在「工作流或 .py 源码的时间戳/大小」或「模型目录的文件数、总体积、最新改动时间」变化时自动失效；"
                 "想强制重扫就点刷新（scan(force=True)），别手动删缓存文件。")
    notes.append("扫描不会打开任何工作流或模型内容之外的东西，也不会联网；"
                 "模型目录里非权重的文件（配置、json、txt 等）只统计体积，不参与判断。")
    return notes


def _do_scan(errors, stages):
    """真正干活的那一趟。t0 由调用方在 scan() 里起。"""
    global _CORPUS, _CORPUS_MARK
    # ---- 1. 磁盘：并行走三棵树（三块不同区域，串行纯属浪费） ----
    t0 = time.perf_counter()
    box = {}

    def _run_models():
        box["models"] = _stat_models(errors)

    def _run_sources():
        box["sources"] = _stat_sources(errors)

    def _run_workflows():
        box["workflows"] = _stat_workflows(errors)

    threads = [threading.Thread(target=f, name="modelscan-" + f.__name__) for f in
               (_run_models, _run_sources, _run_workflows)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    stages["walk_s"] = round(time.perf_counter() - t0, 2)

    all_files = box.get("models") or []
    src_meta = box.get("sources") or []
    wf_texts = box.get("workflows") or []

    if not all_files:
        errors.append("models: 没扫到任何文件（目录不存在或没权限？）：%s" % MODELS_DIR)

    models_sig = _models_sig(all_files)
    sources_sig = _sources_sig(src_meta)
    wf_sig = {"files": len(wf_texts),
              "newest_mtime": _newest_mtime([p for _n, p, _t in wf_texts])}

    # ---- 2. 缓存判定：指纹一致就直接返回磁盘上的上一份 ----
    cache = _read_cache(errors)
    if cache is not None and not any(e.startswith("cache:") for e in errors):
        same = (cache.get("sig_models") == models_sig
                and cache.get("sig_sources") == sources_sig
                and cache.get("sig_workflows") == wf_sig)
        if same and cache["data"].get("models_dir") == MODELS_DIR:
            stages["cache"] = "hit"
            data = dict(cache["data"])
            data["cached"] = True
            data["stages"] = stages
            return data
    stages["cache"] = "miss"

    # ---- 3. 权重清单 ----
    weights = []
    for rel, size, mtime, atime in all_files:
        if os.path.splitext(rel)[1].lower() in WEIGHT_EXT:
            weights.append({"rel": rel, "name": os.path.basename(rel), "size": size,
                            "mtime": mtime, "atime": atime})

    # ---- 4. 工作流引用（按文件名匹配，大小写不敏感；反向扫一遍即可） ----
    t1 = time.perf_counter()
    lower_names = {w["name"].lower() for w in weights}
    # 绝大多数权重名不带 token 边界字符，`_names_in` 一遍线性扫描就能认出来。
    # 只有「分词抓不整」的名字（带空格/括号/引号等，正常命名里很少）才退回逐个全文本查找，
    # 兜住内嵌文本里文件名没有引号包着的情况。工作流 JSON 合计约 10 MB，早期版本对 332 个
    # 名字各做一次全文本查找、45 × 332 次下来这一步是主要热点之一。
    odd_names = sorted(b for b in lower_names
                       if any(c in _TOKEN_STOP for c in b) or not _WORDS.fullmatch(b))
    wf_of = {}
    for wname, _wpath, text in wf_texts:
        for base in sorted(_names_in(text, lower_names)):
            wf_of.setdefault(base, []).append(wname)
        for base in odd_names:
            if base in text:
                wf_of.setdefault(base, []).append(wname)
    used_names = set(wf_of)
    stages["workflows_s"] = round(time.perf_counter() - t1, 2)
    stages["odd_names"] = len(odd_names)

    # ---- 5. 源码语料 + 「谁提到了它」索引 ----
    t2 = time.perf_counter()
    want = (sources_sig.get("files"), sources_sig.get("digest"))
    corpus = _CORPUS
    if corpus is None or _CORPUS_MARK != want:
        corpus = _load_corpus(src_meta, errors)
        _CORPUS = corpus
        _CORPUS_MARK = want
    basenames = sorted(lower_names - used_names)
    # 「谁提到了它」的索引必须同时覆盖文件名和路径两种问法，否则 `_classify` 里的
    # `rel_bs in where` / `tail in where` 永远为假，auto_path 会整类塌进 auto_name。
    needles = set(basenames)
    for w in weights:
        b = w["name"].lower()
        if b in used_names:
            continue
        rb = w["rel"].replace("/", "\\").lower()
        segs = [p for p in rb.split("\\") if p]
        needles.add(rb)                       # 完整相对路径（反斜杠写法）
        needles.add(rb.replace("\\", "/"))    # 完整相对路径（正斜杠写法）
        if len(segs) >= 2:
            tail = "\\".join(segs[-2:])       # 末两段：diffusers 仓库里 basename 没意义，
            needles.add(tail)                 # 但「仓库\子目录\文件」有 —— 7 个 auto_path 里
            needles.add(tail.replace("\\", "/"))   # 有 3 个只靠这条规则才命中
    where = _build_where(corpus, sorted(needles))
    stages["sources_s"] = round(time.perf_counter() - t2, 2)
    stages["corpus_files"] = len(corpus)

    # ---- 6. 分类 + 组装 ----
    t3 = time.perf_counter()
    load_info, hook_rel, hook_base = _load_hook(errors)
    tier_stat = {k: [0, 0] for k in TIER_ORDER}
    autoload = {}
    unref_count = unref_bytes = 0
    items = []
    for w in weights:
        rel, base, size = w["rel"], w["name"].lower(), w["size"]
        refs = sorted(wf_of.get(base, ()))
        if refs:
            tier, evidence = "used", []
        else:
            tier, evidence = _classify(rel, base, corpus, where, errors)
        w["refs"] = refs
        tier_stat.setdefault(tier, [0, 0])
        tier_stat[tier][0] += 1
        tier_stat[tier][1] += size
        if not refs:
            unref_count += 1
            unref_bytes += size
        top = rel.split(os.sep)[0].lower()
        if top in AUTOLOAD_DIRS:
            slot = autoload.setdefault(top, [0, 0, 0, 0])
            slot[0] += 1
            slot[1] += size
            if not refs:
                slot[2] += 1
                slot[3] += size
        hs = hook_rel.get(rel.replace("/", "\\").lower()) or hook_base.get(base)
        items.append({
            "rel": rel.replace("/", "\\"),
            "name": w["name"],
            "top": rel.split(os.sep)[0],
            "size": size,
            "size_h": _fmt_bytes(size),
            "mtime": _fmt_time(w["mtime"]),
            "atime": _fmt_time(w["atime"]),
            "refs": refs,
            "ref_count": len(refs),
            "tier": tier,
            "tier_label": TIER_ZH.get(tier, tier),
            "evidence": evidence[:MAX_EVIDENCE],
            "loads": {"count": hs[0] if hs else 0, "last": _fmt_time(hs[1]) if hs else None},
        })
    items.sort(key=lambda x: (-x["size"], x["rel"].lower()))
    stages["classify_s"] = round(time.perf_counter() - t3, 2)

    # bytes_total 只累加**权重**：这是用户真正关心的「我这 680 GB 模型」。
    # models 树下还有配置 json / 图片 / 文本之类的零碎文件（约 14 GB），单独用
    # bytes_all 报出来 —— 把两者混在一个数里会让「模型占了多少」这件事说不清。
    bytes_total = sum(w["size"] for w in weights)
    bytes_all = sum(f[1] for f in all_files)
    data = {
        "version": VERSION,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": None,                      # 由 scan() 填
        "cached": False,
        "errors": list(errors),
        "models_dir": MODELS_DIR,
        "workflow_dir": WORKFLOW_DIR,
        "workflows_scanned": len(wf_texts),
        "weights": len(weights),
        "files_total": len(all_files),
        "bytes_total": bytes_total,
        "bytes_total_h": _fmt_bytes(bytes_total),
        "bytes_all": bytes_all,
        "bytes_all_h": _fmt_bytes(bytes_all),
        "unref": {"count": unref_count, "bytes": unref_bytes, "bytes_h": _fmt_bytes(unref_bytes)},
        "tiers": {k: {"count": tier_stat[k][0], "bytes": tier_stat[k][1],
                      "bytes_h": _fmt_bytes(tier_stat[k][1]),
                      "label_zh": TIER_ZH[k], "label_en": TIER_EN[k]} for k in TIER_ORDER},
        "autoload_dirs": [{"dir": k, "count": v[0], "bytes": v[1], "bytes_h": _fmt_bytes(v[1]),
                           "unref_count": v[2], "unref_bytes": v[3],
                           "unref_bytes_h": _fmt_bytes(v[3])}
                          for k, v in sorted(autoload.items(), key=lambda kv: (-kv[1][1], kv[0]))],
        "items": items,
        "load_hook": load_info,
        "notes": [],
        "stages": stages,
        "source_files": len(src_meta),
        "sig_models": models_sig,
        "sig_sources": sources_sig,
        "sig_workflows": wf_sig,
    }
    data["notes"] = _notes(data)
    return data


def _read_cache(errors):
    """读磁盘缓存；坏文件/版本不符 → 当没有（不抛，交给调用方重扫）"""
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        errors.append("cache: 读不了旧缓存，将重新扫描（%s: %s）" % (type(e).__name__, e))
        return None
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        return None
    if not isinstance(raw.get("data"), dict) or not isinstance(raw["data"].get("items"), list):
        return None
    return raw


def _write_cache(data, models_sig, sources_sig, wf_sig, errors):
    """原子写缓存：先写 .tmp 再 replace，避免半截 JSON 让后续每次都重扫"""
    payload = {"version": VERSION, "at": time.time(),
               "sig_models": models_sig, "sig_sources": sources_sig, "sig_workflows": wf_sig,
               "data": data}
    tmp = CACHE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE_FILE)
    except OSError as e:
        errors.append("cache: 写不了缓存（不影响本次结果）：%s: %s" % (type(e).__name__, e))
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------
# 五、对外 API
# --------------------------------------------------------------------------
def scan(force=False):
    """
    清点 + 使用分析。返回一个大字典（结构见文件头与 README）。

    force=False 时：
      1) 进程内有结果 → 直接返回（几乎零开销）；
      2) 否则比指纹，指纹没变 → 用 `_modelscan_cache.json` 里的上一份；
      3) 都没有 → 全量扫一遍并写缓存。
    force=True 无条件重扫（忽略内存与磁盘缓存）。
    无论哪种情况都不抛异常：问题都进 `errors`。
    """
    t0 = time.perf_counter()
    errors = []
    stages = {}
    with _LOCK:
        if not force and _MEM["data"] is not None:
            data = dict(_MEM["data"])
            data["cached"] = True
            data["seconds_now"] = round(time.perf_counter() - t0, 3)
            return data
        try:
            data = _do_scan(errors, stages)
        except Exception as e:                 # 兜底：绝不让前端白屏
            import traceback
            traceback.print_exc()
            data = None
            errors.append("scan: %s: %s" % (type(e).__name__, e))
        if data is None:
            data = _empty(errors)
        data["errors"] = list(data.get("errors") or []) + [e for e in errors
                                                           if e not in (data.get("errors") or [])]
        if not data.get("cached"):
            data["seconds"] = round(time.perf_counter() - t0, 1)
            _write_cache(data, data.get("sig_models"), data.get("sig_sources"),
                         data.get("sig_workflows"), errors)
        data["seconds_now"] = round(time.perf_counter() - t0, 3)
        _MEM["data"] = data
        _MEM["at"] = time.time()
        _MEM["seconds"] = data.get("seconds")
        return data


def _empty(errors):
    """极端情况下也要给出结构完整的空结果（前端不用做 null 判断）"""
    return {
        "version": VERSION, "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": None, "cached": False, "errors": list(errors),
        "models_dir": MODELS_DIR, "workflow_dir": WORKFLOW_DIR, "workflows_scanned": 0,
        "weights": 0, "files_total": 0, "bytes_total": 0, "bytes_total_h": "0 B",
        "bytes_all": 0, "bytes_all_h": "0 B",
        "unref": {"count": 0, "bytes": 0, "bytes_h": "0 B"},
        "tiers": {k: {"count": 0, "bytes": 0, "bytes_h": "0 B", "label_zh": TIER_ZH[k],
                      "label_en": TIER_EN[k]} for k in TIER_ORDER},
        "autoload_dirs": [], "items": [],
        "load_hook": {"installed": os.path.exists(LOAD_HOOK_FILE), "records": 0,
                      "last": None, "file": LOAD_HOOK_FILE},
        "notes": _notes({}), "stages": {}, "source_files": 0,
    }


def cache_info():
    """
    缓存状态。`at` 是上一份结果的时间（没有缓存时为 0），`age` 是它到现在过了多少秒。
    `cached` 表示进程内是否已经有现成结果。
    """
    at = 0.0
    if _MEM["data"] is not None:
        at = float(_MEM.get("at") or 0.0)
    exists = os.path.exists(CACHE_FILE)
    mtime = None
    if exists:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
        except OSError:
            mtime = None
    if not at and mtime:
        at = mtime
    return {
        "at": at,
        "age": (time.time() - at) if at else None,
        "cached": _MEM["data"] is not None,
        "cache_file": CACHE_FILE,
        "cache_mtime": _fmt_time_full(mtime),
        "cache_exists": exists,
        "cache_bytes": (os.path.getsize(CACHE_FILE) if exists else 0),
        "mem_seconds": _MEM.get("seconds"),
        "version": VERSION,
    }


def invalidate():
    """丢掉进程内结果（磁盘缓存保留，下次仍然先比指纹）。"""
    with _LOCK:
        _MEM["data"] = None
        _MEM["at"] = 0.0


def summary():
    """给「模型分析」页眉用的一行小摘要；没扫过就返回 None（不触发扫描）。"""
    d = _MEM["data"]
    if not d:
        return None
    return {"generated": d.get("generated"), "weights": d.get("weights"),
            "bytes_total_h": d.get("bytes_total_h"),
            "unref": d.get("unref"),
            "nobody": (d.get("tiers") or {}).get("nobody")}


if __name__ == "__main__":                     # 手动跑一遍，方便校数
    import sys
    t = time.time()
    res = scan(force="--force" in sys.argv)
    print("scan %.1fs cached=%s weights=%d %s" % (time.time() - t, res["cached"],
                                                  res["weights"], res["bytes_total_h"]))
    print("unref:", res["unref"])
    for k in TIER_ORDER:
        v = res["tiers"][k]
        print("  %-10s %3d 个 %9s  %s" % (k, v["count"], v["bytes_h"], v["label_zh"]))
    print("stages:", res.get("stages"))
    print("errors:", res.get("errors"))
