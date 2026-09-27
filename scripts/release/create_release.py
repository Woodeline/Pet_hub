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
TAG = "v0.6.1"
TARGET_COMMITISH = "main"
RELEASE_NAME = "v0.6.1 —— 外置词库 · 卡片化界面 · 中性配色"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXE_PATH = REPO_ROOT / "dist" / "desktop-pet.exe"
ASSET_NAME = "desktop-pet.exe"
#: 发布说明里的全量测试数（发布前以 pytest --collect-only -q 实测为准）
TESTS_TOTAL = 1324

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
| [`desktop-pet.exe`](https://github.com/{owner}/{repo}/releases/download/{tag}/desktop-pet.exe) | {size:.1f} MB | Windows 10 / 11 x64 |

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

## ✨ {tag} —— 外置词库 · 卡片化界面 · 中性配色

相对 `v0.6.0` 的小步功能版。

### 📚 外置词库（日语学习）

- 支持外置词库文件 `%APPDATA%\\desktop-pet\\jlpt_words_extra.json`：启动时与内置 500 词合并（id 去重、外置覆盖）
- 托盘「日语学习 → 导入词库…」一键导入 JSON 词库，格式非法给出明确报错
- 附带 OpenJLPT（CC BY-SA）转换脚本与 **7238 词全中文释义词库**（N1~N5 全覆盖，词性开头、`;` 分义项）
- 日语学习池耗尽修复：词池学完不再空转，切等级 / 导入词库 / 跨日自动恢复

### 🎨 界面改版

- 词库 / 详情 / 日志三窗口卡片化：圆角卡片 + Tab 下划线选中
- 全套配色中性化：白底近黑浅灰 + 绿点缀，全局 Microsoft YaHei
- 气泡描边细化（2.2 → 1.0 淡灰细线），贴纸感保留、不再厚重

### 🧹 维护

- 移除 skins 目录遗留的 `msg_conf.json`，下载脚本加跳过清单防回潮

### ✅ 验证

| 检查项 | 结果 |
|---|---|
| 全量自动化测试 | **{tests} 项全绿**（Python 3.13 + PySide6 offscreen） |
| 词库自检 | 7238 条外置词过 `parse_bank_file`：id 全唯一、五级覆盖、无空释义 |
| 打包版实测 | 冒烟启动 / 词库导入 / 三窗口卡片化 UI |

---

## 🔖 版本历史

| 引用 | 指向 | 说明 |
|---|---|---|
| `main` / `{tag}` | `{commit}` | 本版本 |
| `v0.6.0` | `e49abd6` | 主题系统 · 皮肤包 MOD · 气泡台词自定义 |
| `v0.5.1` | `3e6bb2c` | 日语学习「仅展示一次」修复补丁 |
| `v0.5.0` | `9c02608` | 上一正式版本 |
""".format(
    owner=OWNER,
    repo=REPO,
    tag=TAG,
    size=SIZE,
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
