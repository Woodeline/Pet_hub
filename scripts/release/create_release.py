"""幂等发布脚本：建 GitHub Release + 上传 exe 资产（走 api/uploads.github.com）。

用法（GH_TOKEN 从环境变量读，不落盘）::

    set GH_TOKEN=<PAT>
    python scripts/release/create_release.py

行为：

- 建 Release 用 api.github.com（POST /releases）；tag 已存在则复用，否则按
  ``TARGET_COMMITISH`` 创建
- 传资产用 uploads.github.com（http.client + OpenSSL，规避 curl schannel 吊销检查）
- 幂等：先查 tag 是否已有 release，有则复用 id；同名资产先 DELETE 再 POST
- SHA-256 与文件大小在运行时从实际 exe 计算，避免手工登记出错

注意：**只上传 exe，不上传任何皮肤素材**（skins/*.rar 属第三方版权内容，
见 Release 正文「皮肤与素材说明」与仓库 .gitignore 注释）。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
OWNER = "Woodeline"
REPO = "Pet_hub"
TAG = "v0.6.3"
TARGET_COMMITISH = "main"
RELEASE_NAME = "v0.6.3 —— 学习统计 · 错题本 · 多词库 · 词库纠错"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXE_PATH = REPO_ROOT / "dist" / "desktop-pet.exe"
ASSET_NAME = "desktop-pet.exe"
#: 发布说明里的全量测试数（发布前以 pytest --collect-only -q 实测为准）
TESTS_TOTAL = 1704

TOKEN = os.environ.get("GH_TOKEN", "")


def _head_commit() -> str:
    """运行时取当前 HEAD 短哈希（发布说明引用，避免手工登记）。"""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 —— 取不到就不在正文里写具体哈希
        return "HEAD"


def _file_facts() -> tuple[int, str]:
    data = EXE_PATH.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


SIZE, SHA256 = _file_facts()
RELEASE_COMMIT = _head_commit()

BODY = """## ⬇️ 下载（免安装，无需 Python）

| 文件 | 大小 | 适用 |
| --- | --- | --- |
| [`desktop-pet.exe`](https://github.com/{owner}/{repo}/releases/download/{tag}/desktop-pet.exe) | {size_mb:.1f} MB | Windows 10 / 11 x64 |

下载后**双击即可运行** —— 无需安装 Python、无需解压、无需任何附带文件。

- 启动后宠物出现在屏幕右下角；**退出**：右键宠物 → 退出
- 首次启动会慢几秒（单文件版需把内置依赖解压到 `%TEMP%\\_MEIxxxxxx`），属正常现象
- 配置与学习记录写在 `%APPDATA%\\desktop-pet\\`，**绿色免安装**；不需要时删掉该目录即可

**文件校验**（可选，用于确认下载完整）：

```text
大小    : {size} bytes
SHA-256 : {sha256}
```

> 本 exe 由标签 `{tag}`（提交 `{commit}`）的源码构建，构建配置见仓库根目录
> `desktop-pet-onefile.spec`。

---

## 🎨 皮肤与素材说明（发布范围声明）

- 本程序与本 Release **不包含、不分发任何皮肤素材**：仓库与 Release 资产中均无
  第三方版权的图片 / 音频文件。
- 程序原生支持 **DyberPet 社区皮肤包格式（MOD）**：把获取到的皮肤包放入 exe 同目录的
  `skins/` 文件夹，即可在托盘「外观 → 皮肤」中切换，超大画布自动等比适配。
- 本地开发调试时使用的示例皮肤素材来源于开源项目
  [ChaozhongLiu/DyberPet_GenshinImpact](https://github.com/ChaozhongLiu/DyberPet_GenshinImpact)，
  在此致谢原作者的开源贡献；素材版权归原作者所有，请前往原项目按其开源许可获取使用。

---

## ✨ {tag} —— 学习统计 · 错题本 · 多词库 · 词库纠错

相对 `v0.6.2` 的**学习数据与管理大版本**（统计 / 错题本 / 数据 / 更新 / 弹簧 /
皮肤 / 多词库七个功能批次 + 词库纠错），并附喇叭 tooltip 黑块修复。

### 📊 学习统计面板

- 托盘「日语学习 → 学习统计…」：概览卡 + **近 15 周打卡热力图**（悬停看当日
  新词 / 复习明细）+ **累计掌握曲线**
- 达成每日新词 / 复习目标时，小猫会以兴奋表情**庆祝**（受气泡开关与睡觉守卫约束）

### 📕 错题本

- **零新增存储**：从复习「忘了」的每日记录自动聚合易错词，按出错次数与
  最近遗忘时间排序
- 易错词抽词权重 ×2.0（与生词加权叠乘），反复忘记的词自然重现，走既有学习流
- 每日一次托盘提醒（随机延迟，无易错词当日不打扰）；统计窗口新增「易错词」
  区块，双击直达详情

### 💾 数据管理（导出 / 备份 / 还原）

- 托盘「数据管理…」：**Anki TSV** 导出（文本导入直用）、**CSV** 导出
  （已掌握词含 SRS 字段、学习记录全日期降序）
- **一键备份**：全部学习数据打包为 zip（含多词库与纠错记录）；**还原**走
  原子写，既有文件自动 `.pre-restore` 留档；版本不符 / 路径穿越 / 非 zip
  显式拒绝

### 🔄 检查更新

- 托盘「检查更新」手动查询 GitHub Releases；「自动检查更新（每周）」默认关
- 语义化版本比较，**脏 tag 一律不更新**（宁可漏报不误报）；仅发现新版才提示，
  查询失败也按 7 天节流，不反复打扰

### 🐱 耳尾弹簧物理

- 拖拽拎起 / 游走走位的窗口位移会激励耳朵与尾巴**惯性甩动 + 余韵回摆**
- 半隐式积分 + 固定子步长，帧率无关（30/60/8fps 同终态）且确定性复现；
  无激励时姿态与旧版逐位一致，像素零回归
- 「减少动效」开启时直通关闭；渲染器零改动

### 🎭 皮肤 cross-fade + 社区包元数据

- 切换皮肤 **0.6s 淡入淡出**（旧包淡出 / 新包淡入），不再硬切闪屏；
  「减少动效」下直切终态
- 皮肤包支持可选 `meta`（名称 / 作者 / 版本 / 致谢），皮肤菜单显示社区名；
  附自检工具 `tools/validate_skin_pack.py` 与社区包制作指南（docs/skin-pack.md §8）

### 📚 多词库管理

- 托盘「日语学习 → **词库管理…**」（原「导入词库…」升级）：逐库启用 / 停用 /
  删除（二次确认）/ 拖拽或文件对话框导入
- 按导入顺序合并（同 id 后来者覆盖）；旧 `jlpt_words_extra.json` 启动时
  **自动迁移**；备份自动收录各库文件

### ✏️ 词库纠错

- 学习泡泡「纠错」胶囊 / 详情窗铅笔入口：改**表记 / 读音 / 翻译 / 释义**，
  读音强制纯假名校验
- **覆盖层机制**：只写 `corrections.json` 记录，词库文件**永不改写**；
  可一键撤销（恢复最初原值）；随备份整体迁移
- 纠错后当前词立即以新值重显；已掌握词的 SRS 阶段 / 到期**原样保持**
  （只同步快照字段），详情缓存自动失效

### 🛠️ 修复

- 喇叭 tooltip 黑块：无选择器的 `setStyleSheet` 会把规则泄漏给 tooltip 窗口，
  透明底声明现全部带类选择器

### ⚙️ 配置变更

- 新增 `weak_review_enabled`（错题本提醒，默认开）、`update_check_enabled`
  （每周自动检查更新，默认关）：旧配置文件**无需手动迁移**，缺失时自动回落
  默认值

---

## 🔖 版本历史

| 引用 | 指向 | 说明 |
|---|---|---|
| `main` / `{tag}` | `{commit}` | 本版本 |
| `v0.6.2` | `bfe00da` | 单词发音 · 记忆曲线 · 学习闭环 |
| `v0.6.1` | `d357411` | 外置词库 · 卡片化界面 · 中性配色 |
| `v0.6.0` | `e49abd6` | 主题系统 · 皮肤包 MOD · 气泡台词自定义 |
| `v0.5.1` | `3e6bb2c` | 日语学习「仅展示一次」修复补丁 |
| `v0.5.0` | `9c02608` | 上一正式版本 |
""".format(
    owner=OWNER,
    repo=REPO,
    tag=TAG,
    size=SIZE,
    size_mb=SIZE / 1048576,
    sha256=SHA256,
    commit=RELEASE_COMMIT,
    tests=TESTS_TOTAL,
)


def _api(method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    """调 api.github.com，返回 (status, body_str)。"""
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "wb-release",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
    except Exception as e:  # noqa: BLE001 —— 网络类异常统一走重试
        return 0, f"{type(e).__name__}: {e}"


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    """带指数退避重试的 api 调用。"""
    st, body = 0, ""
    for i in range(8):
        st, body = _api(method, path, payload)
        if st and st < 500:
            return st, body
        time.sleep(min(2**i * 0.5, 6))
    return st, body


def get_release_by_tag() -> dict | None:
    st, body = call("GET", f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}")
    if st == 200:
        return json.loads(body)
    return None


def create_release() -> dict:
    payload = {
        "tag_name": TAG,
        "target_commitish": TARGET_COMMITISH,
        "name": RELEASE_NAME,
        "body": BODY,
        "draft": False,
        "prerelease": False,
        "make_latest": "true",
    }
    st, body = call("POST", f"/repos/{OWNER}/{REPO}/releases", payload)
    if st not in (200, 201):
        print(f"建 Release 失败：status={st} body={body[:300]}")
        sys.exit(1)
    rel = json.loads(body)
    print(f"Release 已创建：id={rel['id']} tag={rel['tag_name']}")
    return rel


def list_assets(rid: int) -> list[dict]:
    st, body = call("GET", f"/repos/{OWNER}/{REPO}/releases/{rid}/assets")
    if st == 200:
        return json.loads(body)
    return []


def delete_asset(aid: int) -> int:
    st, _ = call("DELETE", f"/repos/{OWNER}/{REPO}/releases/assets/{aid}")
    return st


def upload_asset(rid: int) -> dict | None:
    """用 http.client + OpenSSL 走 uploads.github.com，显式 Content-Length。"""
    ctx = ssl.create_default_context()
    body = EXE_PATH.read_bytes()
    conn = http.client.HTTPSConnection("uploads.github.com", timeout=900, context=ctx)
    conn.request(
        "POST",
        f"/repos/{OWNER}/{REPO}/releases/{rid}/assets?name={ASSET_NAME}",
        body=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
            "User-Agent": "wb-release",
        },
    )
    resp = conn.getresponse()
    status = resp.status
    resp_body = resp.read().decode()
    conn.close()
    if status not in (200, 201):
        print(f"上传失败：status={status} body={resp_body[:300]}")
        return None
    asset = json.loads(resp_body)
    print(f"资产已上传：id={asset['id']} size={asset['size']} digest={asset.get('digest')}")
    return asset


def main() -> None:
    if not TOKEN:
        print("缺少 GH_TOKEN")
        sys.exit(1)
    if not EXE_PATH.is_file():
        print(f"找不到 {EXE_PATH}，请先打包")
        sys.exit(1)
    print(f"本地 exe：size={SIZE} sha256={SHA256}")

    rel = get_release_by_tag()
    if rel is None:
        rel = create_release()
    rid = rel["id"]
    print(f"release id={rid}")

    # 幂等：同名资产先删
    for a in list_assets(rid):
        if a["name"] == ASSET_NAME:
            print(f"发现同名资产 id={a['id']}，删除后重传")
            delete_asset(a["id"])

    asset = upload_asset(rid)
    if asset is None:
        print("上传未完成")
        sys.exit(1)

    # 校验：服务端 digest == 本地 sha256
    digest = asset.get("digest", "")
    if digest and digest == f"sha256:{SHA256}":
        print("✅ digest 匹配，上传完整")
    else:
        print(f"⚠️ digest 不匹配：服务端={digest} 本地=sha256:{SHA256}")

    print("DONE")


if __name__ == "__main__":
    main()
