# X-WIDE Plugin & Model Manager

<img src="https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/logo-wordmark.png" alt="X-WIDE — I BELIEVE" width="360">

**English** | [中文](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/README.md)

![version](https://img.shields.io/badge/version-1.1.0-blue)
![license](https://img.shields.io/badge/license-GPL--3.0-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

A **fully local, read-only-first** manager for ComfyUI custom nodes (plugins): it puts "why is startup slow, which plugins are dragging, who depends on whom, and which models nobody actually uses" on the table.

Current version: **1.1.0** (first release — five tabs plus the optional autopilot) — see [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md); the ready-made release notes for this version are in [docs/RELEASE_NOTES_v1.1.0.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/RELEASE_NOTES_v1.1.0.md).

**The only action that touches the filesystem is Disable / Enable**, and all it does is **rename a folder**:

```
ComfyUI/custom_nodes/<pack>   ⇄   ComfyUI/custom_nodes/<pack>.disabled
```

`.disabled` is ComfyUI's own convention (`nodes.py` skips it). **No file is ever deleted**, and renaming it back restores the plugin. Disable / enable take effect only after a **ComfyUI restart**.

> **It does not delete models, does not touch pip packages, does not go online, and does not modify any file of ComfyUI itself.** The models page only offers "open folder" — there is no delete button anywhere.

Current version: **1.1.0** (first release) — see [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md).

> **Publishing to the Comfy Registry is a manual step.** The GitHub Actions workflow in this
> repository is manual-trigger only (add `REGISTRY_ACCESS_TOKEN`, then click **Run workflow** on
> the Actions page); **pushing code does not publish a release by itself**. That is deliberate:
> disable / enable touches the filesystem, so the plugin is meant to be tested locally first.
> See [docs/发布指南.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/发布指南.md) for the full steps.

---

## Contents

- [What it looks like](#what-it-looks-like)
- [The five tabs](#the-five-tabs)
- [Safety boundaries (read this first)](#safety-boundaries-read-this-first)
- [Installation](#installation)
- [Usage](#usage)
- [Compatibility](#compatibility)
- [Repository layout](#repository-layout)
- [FAQ](#faq)
- [About the author](#about-the-author)
- [License](#license)
- [Publishing (for maintainers)](#publishing-for-maintainers)

---

## What it looks like

Entry point: ComfyUI's left sidebar → the **X-WIDE** tab (box icon). The sidebar is grouped top to bottom: **brand** (the X-WIDE logo + title + a one-line subtitle, "What slows startup, what depends on what, what breaks if you touch it, which models are unused", plus the **version** badge, the **GPL-3.0** licence badge and a one-line **disclaimer**), **author & links** (GitHub / Bilibili), **autopilot** (the switch, the scope, and the three buttons "show the plan" / "disable as planned…" / "restore what autopilot disabled"), and **common actions** (**"Open full panel"**, **generate report**, **help**, the **中文 / English** switch); **"Open full panel"** opens the five-tab UI in a **new browser tab** (it no longer covers the canvas).

![Sidebar](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/sidebar.png)

![Overview of the five tabs](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/overview.png)

> Every tab below comes with a screenshot, all captured **on a real machine, in a real browser**
> (the full panel is just a web page — the standalone tab is the very same page). The images live in `docs/images/`.
> To see what the "we stop you first" dialog looks like, jump to the second image in ②.

**It is just a web page**: `http://<your host>:<port>/xwide/plugin-manager/ui` — the same page the sidebar's "Open full panel" button opens, in a new browser tab, so you can park it on a second monitor or keep it next to the ComfyUI canvas. This path does not depend on the ComfyUI front end exposing the sidebar API. Tabs are deep-linkable, e.g. `…/ui#packs`, `#workflows`, `#models`, `#log`. The script is loaded **from this plugin's own route** (`/xwide/plugin-manager/web/xwide_plugin_manager.js`), so it still opens when the plugin folder has been renamed or was installed by the Registry under a different folder name (it then falls back to ComfyUI's `/extensions/<folder name>/`).

The header carries the shared controls: **data freshness** (was this generated just now or served from cache, and when), **generate report file / view report**, **中文 ⇄ English** (your choice is remembered) and the built-in help; under the title sits an author line: X-WIDE, the version (click it for the GitHub repository), the repository, the changelog, the Bilibili page and the issue tracker. Clicking **"Re-analyse"** immediately shows `◐ re-analysing… N s elapsed` under the header and locks the button; when it finishes you get "re-analysis finished in X s" — no more "I clicked and nothing happened".

---

## The five tabs

### ① Startup

Reads the startup log and reports the total time from **process start → UI ready**, split into four phases:

| Phase | Meaning |
| --- | --- |
| Bootstrap | interpreter / dependency imports and other pre-start work |
| Pre-startup scripts | front scripts such as `prestartup_script.py` |
| Node imports | the import cost of each `custom_nodes` pack |
| Wrap-up | from the end of imports to the server being ready |

It also reports:

- **Two per-pack cost tables**, one for `prestartup` and one for `import`, so the most expensive pack is obvious at a glance;
- **packs that failed to import** (`IMPORT FAILED` and friends in the log);
- **degradation notices** (a pack that only partially imported, or a capability that did not load).

![Startup tab](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/startup.png)

### ② Plugins

Scans the source and docs of every pack under `custom_nodes` for dependencies. **Four layers of evidence**, each with the original `file:line` text so you can check it yourself:

| Layer | Evidence |
| --- | --- |
| 1 | an `import` statement in the source |
| 2 | dynamic loading (fetching a module by name through `importlib` and the like) |
| 3 | list declarations (the pack name written in a requirements / dependency list) |
| 4 | documentation mentions (README, comments) |

It also scans which node types your workflows use, so every pack gets:

- **startup cost** and **number of registered nodes**;
- **how many workflows use it** and **who references it** (reverse dependency lookup: which enabled packs reference it);
- a **three-colour risk mark**: 🟢 green = safe to clean up / 🟡 yellow = risky / 🔴 red = better left alone (infrastructure packs, or packs that dozens of others depend on);
- **dependency-index scan status**: how many packs were reused, how many rescanned, how long it took, and whether the cache write failed.

> The dependency index is **incremental per pack**: packs whose source has not changed are reused straight from the cache; only changed packs get rescanned.

![Plugins tab](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/plugins.png)

When you disable a pack that **has ties** (referenced by another plugin, or used by a workflow), this
list appears first: it shows the evidence, and the confirmation phrase (`disable <pack name>`) has to be
**typed by hand**. A typo only warns — nothing is executed. This is the layer that stops "one careless
click, then half your nodes are gone".

![Risk confirmation before disabling](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/risk-confirm.png)

### ③ Workflows

For every workflow it lists:

- **last modified / last read time** and an **age bucket** (≤ 7 days / 8–30 days / 31–90 days / > 90 days);
- **which plugins it uses**;
- **whether it references nodes of a disabled plugin**, and **whether it uses node types that are not registered right now** (missing nodes). Missing-node detection **checks the front-end JS first**, so nodes that are only registered in JS are not reported as missing by mistake;
- **reverse lookup**: which workflows use each plugin.

> "Last read time" comes from the filesystem access time. **It is not evidence of use** — many filesystems do not update it, and antivirus / backup / cloud-sync / Explorer previews refresh it. Treat it as a hint only.

![Workflows tab](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/workflows.png)

### ④ Models

A **read-only** inventory of your model folders: total size and count, which models are not referenced by any workflow, and a three-tier split of the unreferenced ones by **reference strength** (named in source / convention folder / mentioned nowhere), each with evidence.

The table has **two views**, switched by the **"group by type"** checkbox under "show one tier at a time" (on by default):

- **Grouped by type**: everything of the same `type` (`unet` / `text_encoders` / `diffusion_models` / `loras` …) goes into one collapsible block, its header reading "N files · total size", the blocks ordered by size — no more scrolling a long flat table to find one kind of model;
- **Flat table**: uncheck it and you get the flat table back, with the "type" column.

The search box is **debounced**: typing does not redraw the whole table on every keystroke (hundreds of rows stay responsive).

**The colour chips under the bar are the filter too**: click "nobody mentioned it" to see just that tier (click again to clear); the selected chip gets a highlighted outline, and it shares one state with the "only one tier" buttons below, so both stay in sync.

The "**convention auto-load folders**" table below (whatever is in there gets loaded) is **collapsed by default** — there is a lot in it, but you do not need it every day.

> **This tab deletes nothing and has no bulk operations.** The only action is **"open folder"**.

![Models tab](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/models.png)

### ⑤ Actions

Every **disable / enable** is appended to `actions.log`: time, target, `old name → new name`, success or failure. The page shows that log and offers **one-click restore**, so you never have to rename folders by hand.

![Actions tab](https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/actions.png)

---

## Safety boundaries (read this first)

1. **The only write operation is a rename.** Disable = rename `custom_nodes/<pack>` to `custom_nodes/<pack>.disabled`; enable = rename it back. This is ComfyUI's own convention (`nodes.py` skips `.disabled`), **no file is deleted**, and no data is lost by renaming.
2. **Disable / enable only take effect after a ComfyUI restart.**
3. **No model deletion**: the models page has no delete button, only "open folder".
4. **No pip manipulation**: it never runs `pip install` / `pip uninstall`, and never removes libraries from your environment.
5. **No network access**: all analysis happens locally; the plugin makes no outbound requests of its own.
6. **No modification of ComfyUI itself**: it only reads logs, workflows and model listings; files it writes live inside its own folder (caches and logs).
7. **Risks are shown before anything is disabled**: the UI lists who references the pack, which workflows use it, and which nodes you may lose. **When there are entanglements you must type a confirmation word** (case-sensitive; the box tells you what to type). **Bulk disable** requires the confirmation word too, and is capped at **60 packs per run**.
8. **Static analysis is not runtime verification**: dependencies come from name matching in source and docs. Packs that degrade silently inside `try/except` can only be confirmed by "disable → restart → read the log". The `file:line` evidence is there so you can judge for yourself.
9. **Optional "autopilot" checkbox** (**unchecked by default**): turning it on **asks for confirmation once** (spelling out the rules and the hard limits); after that **every visit to the Plugins tab runs it automatically** — it scans workflows and dependencies, then disables packs that were **never used by any workflow** or **have not been used for more than N days (default 90)**. Server-side hard limits: **at most 12 per run** (and never more than half of the enabled packs); packs whose source changed within 3 days, packs really `import`ed by another pack, and `KEEP_NEVER` packs are never touched. Each run ends with a result window (what was disabled, estimated saving, failures) plus a one-click restore, and every action is logged on tab ⑤. When it is **not** checked, the plugin **only scans and lets you decide**; the card also offers "show the plan first" (changes nothing) and "restore what autopilot disabled".

> While a run is in progress **all three buttons are locked** (greyed out) and the window shows `◐ disabling… N s elapsed`; clicking "show the plan" or "disable as planned…" repeatedly **still runs it only once**, and the plan and the result appear in the **same window** (so it never looks like it ran twice).
10. **Other launchers' "extensions" lists do not understand the `.disabled` suffix**: a disabled pack still shows up as installed there. So **do all disabling / enabling from this panel**.

### How to roll back

- In the panel: **tab ⑤ "Actions" → click "restore"**;
- By hand: rename `ComfyUI/custom_nodes/<pack>.disabled` back to `ComfyUI/custom_nodes/<pack>`;
- To remove the plugin entirely: delete this folder — it leaves nothing behind (restore any disabled packs as above first).

---

## Installation

**Option 1 — ComfyUI Manager (recommended)**

1. Open Manager → search for **`X-WIDE Plugin & Model Manager`** (or `x-wide`, `plugin manager`);
2. Restart ComfyUI and refresh the page (`Ctrl` + `F5`).

**Option 2 — manual**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager
```

Restart ComfyUI, then hard-refresh the page (`Ctrl` + `F5`).

No extra dependencies: only ComfyUI's bundled `aiohttp` and the Python standard library are used.

> The plugin **does not depend on its own folder name**: `X-WIDE_plugin_model_manager` and `comfyui-x-wide-plugin-model-manager` both work.

---

## Usage

1. Restart ComfyUI and hard-refresh the page;
2. Left sidebar → the **X-WIDE** tab → **"Open full panel"** (it opens in a new browser tab; you can also visit `http://<host>:<port>/xwide/plugin-manager/ui` directly);
3. Work through the tabs: start with **① Startup** to find what is slowing the boot, then **② Plugins** for the three-colour risk marks, and only then consider disabling;
4. Before disabling anything, **expand it** and read the evidence (does a workflow use it? does another pack reference it?);
5. Disable → **restart ComfyUI** → go back to **① Startup** to compare boot time, and to **③ Workflows** to check for missing nodes;
6. If something breaks: **⑤ Actions → restore**, then restart.

---

## Compatibility

- **OS**: Windows / macOS / Linux;
- **ComfyUI**: 0.3 and above (developed and measured on ComfyUI **0.38.2** + front end 1.53.6); **Python 3.10+**;
- **Dependencies**: **the Python standard library plus ComfyUI's own bundled `aiohttp`** — nothing else is installed. `psutil` is an optional accelerator (used when present, otherwise per-platform system calls are used);
- **Front end**: the sidebar entry needs a recent ComfyUI front end (one that exposes `registerSidebarTab`). **On an older front end without that API the sidebar entry does not appear** (a line is printed to the console), but **the web page always works**, independently of the front-end version: open `http://<host>:<port>/xwide/plugin-manager/ui` — the HTTP routes work there too;
- **No hard-coded paths**: it first **asks ComfyUI itself** (`folder_paths`) for `custom_nodes` / `models` / `user` / workflows / log locations, then derives them from the plugin's own location, and only then falls back to the platform's usual locations; every one of them can be overridden by an environment variable;
- **Environment variable overrides**:

  | Variable | What it overrides |
  | --- | --- |
  | `XWIDE_COMFY_ROOT` | the ComfyUI root (other paths are derived from it) |
  | `XWIDE_NODES_DIR` | the `custom_nodes` folder |
  | `XWIDE_MODELS_DIR` | the `models` folder |
  | `XWIDE_WORKFLOWS_DIR` | the workflows folder |
  | `XWIDE_LOG_FILE` | the ComfyUI log file to parse |
  | `XWIDE_USER_DIR` | ComfyUI's `user` folder |
  | `XWIDE_DATA_DIR` | this plugin's own data folder (caches / logs) |
  | `XWIDE_SERVER` | the ComfyUI server address to talk to |
  | `XWIDE_MODEL_LOGS` | set to `0` to turn the optional model-load logging hook off |

  > If you do not need any of them, **set nothing** — the plugin finds everything by itself. This
  > README does not restate the code; the code is the final authority.
  >
  > **A read-only plugin folder is fine**: data files (caches / `actions.log` / model-load records)
  > are written inside the plugin's own folder by default, and fall back to
  > `X-WIDE_plugin_model_manager/` under the `user` folder when that folder is not writable — so a
  > packaged install with a read-only `custom_nodes` mount still works.

### How far compatibility has actually been verified (no hand-waving)

| How it was verified | What that covers |
| --- | --- |
| **On a real machine** (Windows + ComfyUI 0.38.2 + Python 3.13) | All five tabs, the disable → restart → restore loop, the autopilot (run when enabled / one-click restore), the full panel (new tab / standalone window), every HTTP route |
| **Automated "another machine" test** | The whole plugin is copied to a temp folder under the name Comfy Registry would install it as (`x-wide-plugin-model-manager`) and exercised in a Python process with **no ComfyUI at all**: path derivation, snapshot fallback, all four data tabs, the autopilot decision, a real disable/restore, out-of-bounds paths and the "never touch itself" guard — 30/30 checks pass |
| **Automated branch test** (platform constants and `subprocess` replaced by fakes, then each branch really runs) | Linux: the `xdg-open` → `gio open` → `nautilus` fallback chain, opening the containing folder when locating a file, a clear error when none of the three exist, `/proc` start-time (`btime` + `starttime / SC_CLK_TCK`), and an empty result (not an exception) when `btime` is missing; macOS: `open` / `open -R`, and the no-`psutil` fallback; Windows: `os.startfile` for a folder and `explorer /select,` for a file; plus `filetime_to_unix`, `server_url()` defaults and the `XWIDE_SERVER` override, and checks that importing the plugin does no work (no `prestartup_script.py`, no top-level loops / bare calls / `atexit` / `Timer` / `time.sleep` in the library modules) — 29/29 checks pass |
| **Code review only (never run on that hardware)** | How those branches actually behave on real macOS / Linux (command availability, desktop-environment differences, permissions) |

> In one line: **Windows is machine-tested**; every macOS / Linux branch exists and has a fallback
> (it degrades or falls back to the log instead of failing) and an automated branch test has been run,
> but it has **not** been run on that hardware. Issues from macOS / Linux users are welcome.
>
> The other direction matters too: when the plugin is imported **outside a ComfyUI process**
> (a script, another tool), this process's node registry is empty, so the on-disk snapshot is used
> instead — it will never suggest disabling a plugin merely because "nobody seems to use it".

### Optional model-load logging hook

- It only **records**; it never **blocks** a model load;
- Turn it off with `XWIDE_MODEL_LOGS=0` (or `off` / `false` / `no` / `none`);
- If the hook itself errors it **cannot affect loading** (exceptions are swallowed);
- The log file lives in this plugin's data folder.

---

## Repository layout

```
comfyui-x-wide-plugin-model-manager/
├── __init__.py                 # local API routes + optional model-load logging hook
├── analyzer.py                 # analysis: source/doc dependencies, workflows, startup log parsing
├── collector.py                # turns analysis results into the JSON the UI consumes + in-memory cache
├── pages.py                    # startup check / workflow analysis / models bridge / load records
├── modelscan.py                # model folder scan and tiering
├── manager.py                  # disable / enable (rename + guards + actions.log + bulk)
├── autopilot.py                # "autopilot": pick candidates + hard guards + run + one-click restore
├── web/xwide_plugin_manager.js # front end: sidebar entry + the full panel (five tabs)
├── web/logo_xwide.png          # brand logo (sidebar / header wordmark)
├── web/logo_xwide_icon.png     # square icon (Registry Icon)
├── pyproject.toml              # Comfy Registry metadata
├── CHANGELOG.md                # changelog
├── NOTICE                      # copyright and provenance
├── LICENSE                     # GPL-3.0
└── docs/                       # publish guide + release notes + images (docs/images/: README screenshots, brand logo-wordmark.png, Registry banner.png)
```

At runtime the plugin also creates a few cache / log files in its own folder (`_*.json`,
`_model_loads.jsonl`, `actions.log`). They are **local only** and are already covered by
`.gitignore`; if the plugin folder is not writable they are written under the `user` folder instead.

---

## FAQ

**Q: Will it delete my plugins or models?**
A: No. The only write operations are renaming `custom_nodes/<pack>` to `<pack>.disabled` and writing its own caches / logs. The models page has no delete function at all.

**Q: I disabled a pack but its nodes are still there / still erroring?**
A: Disabling takes effect only after a **ComfyUI restart**. If a workflow still references its nodes, tab ③ "Workflows" lists them as missing nodes.

**Q: I renamed the folder back, but the UI still says "disabled".**
A: The UI serves cached data. Restart ComfyUI, or force a refresh from the panel.

**Q: It asks me to type a confirmation word — what is it?**
A: The UI says so on screen. **Entangled packs** (referenced by other enabled packs, or used by your workflows) require it on purpose: after disabling those, ComfyUI usually does **not** print `IMPORT FAILED` — it **silently loses a few nodes**, which is very hard to spot. **Bulk disable requires typing it too, and is capped at 60 packs per run.**

**Q: The first visit to "Plugins" is slow.**
A: The first run rebuilds the dependency index, which scans the source of every pack. Afterwards only packs whose source changed are rescanned and the rest come from the cache. The bottleneck is usually the filesystem (antivirus / cloud sync / indexing drivers slow reads down noticeably).

**Q: The "last read" time says I have not opened a workflow in ages, but I have.**
A: That time comes from the filesystem access time; **many systems do not update it**, and antivirus / backup / cloud sync / Explorer previews refresh it. Treat it as a hint only.

**Q: The models tab says a model is "mentioned nowhere" — can I delete it?**
A: **That tab only tells you nobody mentions it; it never tells you to delete it.** "Mentioned nowhere" is only a **candidate**: it may be a renamed copy, a path assembled dynamically in code, or an experiment never saved as a workflow. This plugin offers no deletion — check it yourself before removing anything.

**Q: Can I turn the model-load logging off?**
A: Yes — set `XWIDE_MODEL_LOGS=0`. It only records, it never blocks.

**Q: Is it safe? Does it upload my data?**
A: No. Everything is analysed locally and the plugin never goes online.

---

## About the author

| | |
| --- | --- |
| <img src="https://raw.githubusercontent.com/XWIDE/comfyui-x-wide-plugin-model-manager/main/docs/images/logo-wordmark.png" alt="X-WIDE" width="160"> | **X-WIDE** |
| GitHub | <https://github.com/XWIDE> |
| Author page (Bilibili) | <https://space.bilibili.com/374064919> |
| Repository / download page | <https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager> |
| Comfy Registry publisher page | <https://registry.comfy.org/publishers/xwide> |
| Issues | <https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/issues> |

---

## License

- Licensed under **GPL-3.0**; the full text is in [LICENSE](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/LICENSE);
- Copyright and provenance notes (including the statement that only ComfyUI's bundled `aiohttp` and the standard library are used) are in [NOTICE](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/NOTICE);
- The change list is in [CHANGELOG.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/CHANGELOG.md).

---

## Publishing (for maintainers)

**Publishing is a manual step**: `.github/workflows/publish_action.yml` keeps only
`on: workflow_dispatch:` (there is no `push` trigger). Once `secrets.REGISTRY_ACCESS_TOKEN` is
configured, go to
<https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/actions/workflows/publish_action.yml>
and click **Run workflow** to publish to the Comfy Registry; **pushing code does not publish a
release by itself**.

That is deliberate — disable / enable touches the filesystem, so **test locally first** (the whole
disable → restart → restore cycle) before publishing. To go back to "publish automatically when
`pyproject.toml` changes on `main`", copy the `push:` snippet provided in the comments at the top of
the workflow file. Full steps: [docs/发布指南.md](https://github.com/XWIDE/comfyui-x-wide-plugin-model-manager/blob/main/docs/发布指南.md).
