#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 GitHub 仓库 ChaozhongLiu/DyberPet_GenshinImpact 下载指定原神角色皮肤包，
适配到 desktop-pet 的 skins/ 目录。

下载通道：ghfast.top 镜像 + raw.githubusercontent.com（绕开 API rate limit）
数据源：本地 .tree_cache.json（git trees 递归树，含全部 blob 的 path）

用法：
    python download_dyberpet_skins.py [角色中文名...]
    不传参数则下载默认列表（兰纳罗/纳西妲/蕈兽）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = "ChaozhongLiu/DyberPet_GenshinImpact"
COMMIT_SHA = "0789950b81802cc51ebeeecfc24be16aaee16e74"

# 中文角色目录名 -> 英文包名
NAME_MAP = {
    "兰纳罗": "Aranara",
    "纳西妲": "Nahida",
    "蕈兽": "Fungi",
    "魈": "Xiao",
    "魈鸟": "XiaoBird",
    "流浪者": "Wanderer",
    "散猫猫": "SanMaoMao",
}

HERE = os.path.dirname(os.path.abspath(__file__))
SKINS_DIR = os.path.abspath(os.path.join(HERE, "..", "skins"))
TREE_CACHE = os.path.join(SKINS_DIR, ".tree_cache.json")

# 镜像前缀（可替换，留空=直连 raw）
MIRROR = "https://ghfast.top/"

CONCURRENCY = 10
TIMEOUT = 30


def raw_url(path):
    quoted = urllib.parse.quote(path)  # 中文路径转义
    raw = f"https://raw.githubusercontent.com/{REPO}/{COMMIT_SHA}/{quoted}"
    return MIRROR + raw if MIRROR else raw


def load_tree():
    if not (os.path.exists(TREE_CACHE) and os.path.getsize(TREE_CACHE) > 1000):
        raise RuntimeError(f"tree 缓存不存在: {TREE_CACHE}，请先获取 tree")
    with open(TREE_CACHE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["tree"]


def download_one(blob, out_path):
    """下载单个文件。已存在且大小一致则跳过。返回 (ok, err)。"""
    size = blob.get("size", -1)
    if os.path.exists(out_path) and size > 0 and os.path.getsize(out_path) == size:
        return True, None
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    url = raw_url(blob["path"])
    last_err = None
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "skin-dl"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
            with open(out_path, "wb") as f:
                f.write(data)
            # 校验大小（避免下到 404 HTML）
            if size > 0 and len(data) != size:
                raise ValueError(f"大小不符: 期望 {size}, 实际 {len(data)}")
            return True, None
        except Exception as e:
            last_err = e
            time.sleep(1.0)
    return False, str(last_err)


def download_role(tree, cn_name, en_name):
    prefix = f"res/role/{cn_name}/"
    blobs = [it for it in tree
             if it["type"] == "blob" and it["path"].startswith(prefix)]
    if not blobs:
        print(f"[跳过] {cn_name}: 未找到文件", flush=True)
        return

    dest = os.path.join(SKINS_DIR, en_name)
    os.makedirs(dest, exist_ok=True)

    total = len(blobs)
    print(f"[下载] {cn_name} -> {en_name} ({total} 个文件, {CONCURRENCY} 线程)",
          flush=True)

    tasks = []
    for blob in blobs:
        rel = blob["path"][len(prefix):]
        out_path = os.path.join(dest, rel.replace("/", os.sep))
        tasks.append((blob, out_path))

    ok = fail = 0
    failed = []
    done = 0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(download_one, b, o): o for b, o in tasks}
        for fut in as_completed(futs):
            out_path = futs[fut]
            try:
                succ, err = fut.result()
            except Exception as e:
                succ, err = False, str(e)
            if succ:
                ok += 1
            else:
                fail += 1
                failed.append(os.path.relpath(out_path, dest))
            done += 1
            if done % 100 == 0 or done == total:
                print(f"  进度 {done}/{total} (成功 {ok}, 失败 {fail})", flush=True)

    print(f"[完成] {en_name}: 成功 {ok}, 失败 {fail}", flush=True)
    if failed:
        print(f"  失败(重跑补齐): {len(failed)} 个 -> {failed[:10]}", flush=True)
    print(flush=True)


def main():
    roles = sys.argv[1:]
    if not roles:
        roles = ["兰纳罗", "纳西妲", "蕈兽"]

    print(f"目标角色: {roles}", flush=True)
    print(f"输出目录: {SKINS_DIR}", flush=True)
    print(f"镜像: {MIRROR or '直连'}", flush=True)
    print(flush=True)

    tree = load_tree()
    print(f"tree 条目数: {len(tree)}", flush=True)
    print(flush=True)

    for cn in roles:
        en = NAME_MAP.get(cn, cn)
        try:
            download_role(tree, cn, en)
        except Exception as e:
            print(f"[错误] {cn}: {e}", flush=True)

    print("全部完成。", flush=True)


if __name__ == "__main__":
    main()
