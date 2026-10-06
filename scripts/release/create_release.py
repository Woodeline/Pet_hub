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
TAG = "v0.6.2"
TARGET_COMMITISH = "main"
RELEASE_NAME = "v0.6.2 —— 单词发音 · 记忆曲线 · 学习闭环"
REPO_ROOT = Path(__file__).resolve().parents[2]
EXE_PATH = REPO_ROOT / "dist" / "desktop-pet.exe"
ASSET_NAME = "desktop-pet.exe"
#: 发布说明里的全量测试数（发布前以 pytest --collect-only -q 实测为准）
TESTS_TOTAL = 1502

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

## ✨ {tag} —— 单词发音 · 记忆曲线 · 学习闭环

相对 `v0.6.1` 的**学习功能大版本**（单词发音 + 间隔重复复习 + 双击学习闭环），
并附右键菜单 / 矢量 / 主题 / 表情的视觉打磨。

### 🔊 单词发音

- 详情窗 / 生词本卡片点击喇叭即听：**有道词典 TTS 为主源**（国内可达），
  Google 翻译 TTS 回退；MP3 按词缓存到 `%APPDATA%\\desktop-pet\\audio_cache`
  （二次点击秒播、离线可播）
- **发音输入优先假名**：防熟字训（如「明後日 = あさって」）被按字面拼读错，
  全词库 7738 条实测 99.9% 走假名
- 播放走系统 winmm/MCI，**零新增依赖**

### 🔁 记忆曲线（间隔重复复习）

- 「记住了」即入**已掌握词库**，按 **1 → 3 → 7 → 14 → 30 → 60 → 120 天**间隔
  阶梯自动安排复习，7 轮毕业进入长期记忆；与生词本区分管理
- 复习泡泡为**主动回忆**形态：隐藏翻译、只给单词 + 假名，点「还记得 / 忘了」
  自评；「忘了」自动退回生词本重学；超时不作答不算遗忘（无痕顺延 1 小时）
- 托盘新增**「已掌握词库…」**窗口：记忆阶段 / 到期 / 毕业状态一目了然，
  支持立即复习、退回生词本、清空；学习记录新增「复习·记得 / 复习·忘了」两态
- **复习节奏门控**：两次复习强制间隔 30~600s（与生词同款节奏，杜绝连环轰炸）；
  **每日复习上限**默认 20（托盘「复习上限」可调 10/20/30/50）；复习不占新词
  每日配额
- 老用户升级免迁移：存量已掌握词从升级次日起陆续自动进入复习

### 🖱️ 双击学习闭环

- 双击单词气泡 = **记生词 + 打开中文五要素详情**，一步完成「不认识 → 深入学」

### 🖱️ 右键菜单 Win11 化

- 全新 `ShadowMenu`：分层窗口 + 自绘高斯柔和阴影 + 白色圆角面板，
  告别 Windows 原生的方块粗阴影；勾选标记 / 子菜单箭头保持原生观感
- 托盘菜单、全部子菜单、宠物右键菜单统一生效

### 🐱 团子猫矢量精致化

- 耳朵：直线三角 → 曲线猫耳 + 粉色内耳，与圆球轮廓无缝衔接
- 爪子：趾缝弧线替代「OO」小圆；尾巴与身体渐变场连续取色（交界无色差）
- 主体描边 3.2 → 2.6：保留贴纸感、整体更轻盈

### 🎄 主题装饰张力强化

- 春：垂柳加长加密 + 花瓣加多；夏：遮阳棚移出遮挡区（完整可见）+ 海浪线 + 太阳加大
- 秋：枫叶更多更大；冬：雪山双峰避让猫身完整可见 + 雪花加多
- 春节：灯笼加大加多（金盖金穗 + 骨架纹）、烟花绽放更饱满

### 😊 表情升级

- 8 个既有表情全面更生动（笑弧 / 瞳孔 / 歪头 / 泪光 / 腮红等逐项调参）
- 新增第 9 表情「敲累了」：连续敲键盘 10 秒自动插播（眯眼喘气 + 汗滴），停手即恢复
- 新增小表演：**假睡偷看**（装睡冒 ZZZ → 偷偷睁眼瞄一眼 → 装回去）、**打嗝**（嗝地弹两下）

### ⚙️ 配置变更

- 新增 `jp_review_daily_limit`（每日复习上限，默认 20）：旧配置文件**无需手动
  迁移**，缺失时自动回落默认值

---

## 🔖 版本历史

| 引用 | 指向 | 说明 |
|---|---|---|
| `main` / `{tag}` | `{commit}` | 本版本 |
| `v0.6.1` | `d357411` | 外置词库 · 卡片化界面 · 中性配色 |
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
