# 皮肤包（MOD）规范

> 版本：1.1（2026-09-22）· 目录结构参照 DyberPet 社区规范，配置 schema 为本项目适配版
> 实现：`core/skin_pack.py`（加载与校验）· `ui/skin_renderer.py`（帧图渲染通道，phase 2 已接入）

## 1. 目录结构

一个皮肤包 = 一个目录，投放到仓库根的 `skins/` 下（该目录已 gitignore，
**绝不入库**）。运行时按包加载：

```
skins/
└── <包名>/                  # 目录名即包名，请使用英文（Windows 中文路径风险）
    ├── pet_conf.json        # 必需：全局层（画布 / 缩放 / 槽位路由）
    ├── act_conf.json        # 必需：动作层（帧序列 / 循环 / 帧率 / 锚点）
    └── action/              # 必需：全部帧图，透明背景 PNG
        └── <前缀>_<序号>.png   # 序号从 0 起连续：stand_0.png, stand_1.png, ...
```

帧图命名规则：`<images 前缀>_<从 0 起的连续序号>.png`；序号断档时断档之后
的帧会被忽略（产生警告）。

## 2. 双层配置 schema 与职责边界

引用方向严格单向：**pet_conf → act_conf → 帧图文件**。

| 层 | 文件 | 职责 | 禁止出现 |
|---|---|---|---|
| 全局层（路由） | `pet_conf.json` | 画布尺寸、整体缩放、「某状态下播哪个动作」 | 任何帧信息 |
| 动作层（资源） | `act_conf.json` | 「一个动作怎么播」：帧前缀/循环/帧率/锚点 | 路由信息；动作间互相引用 |

### 2.1 pet_conf.json（全局层）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `width` | int | 必填 | 全部帧图的最大宽度，1 ≤ w ≤ 160（`BASE_W`） |
| `height` | int | 必填 | 全部帧图的最大高度，1 ≤ h ≤ 180（`BASE_H`） |
| `scale` | float | 1.0 | 整体显示比例（>0），同时影响移动速度的基准 |
| `default` | str | 必填 | 静息动作映射 |
| `drag` | str | 必填 | 被拖拽动作映射 |
| `fall` | str | 必填 | 自由下落动作映射 |
| `left` / `right` / `up` / `down` / `on_floor` / `prefall` / `patpat` / `focus` | str | 可选 | 扩展槽位（phase 2 逐步启用） |
| 其他键 | — | — | **警告容忍**：加载成功但记入 warnings |

槽位值 = `act_conf.json` 中定义的动作名；`default` / `drag` / `fall`
三个槽位缺失即加载失败（**最小动作集实现基线**）。

### 2.2 act_conf.json（动作层）

每条动作 = 动作名为 key，定义对象为 value：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `images` | str | 必填 | 帧图前缀（不得含路径分隔符） |
| `act_num` | int | 1 | 帧序列循环播放次数（**≥1**）。画 1 套循环即可播 N 次，是帧循环复用、避免资源冗余的机制 |
| `frame_refresh` | float | 0.2 | 单帧显示时长（秒，>0）。同一包内建议统一 |
| `anchor` | [int, int] | [0, 0] | 相对固定位置的像素平移修正 [x, y]，用于动作切换时对齐地面/重心 |

未知键警告容忍；解析失败的条目整体拒绝（fail-fast，列出全部问题）。

### 2.3 最小可运行示例

```jsonc
// pet_conf.json
{
  "width": 64, "height": 80, "scale": 1.2,
  "default": "idle",
  "drag": "drag",
  "fall": "fall"
}
```

```jsonc
// act_conf.json —— default 播 1 轮 4 帧；drag/fall 各画 3 帧但循环 2 次（act_num 复用）
{
  "idle": { "images": "stand", "frame_refresh": 0.25 },
  "drag": { "images": "drag", "act_num": 2, "frame_refresh": 0.12, "anchor": [0, 4] },
  "fall": { "images": "fall", "act_num": 2, "frame_refresh": 0.12 }
}
```

对应帧图：`action/stand_0..3.png`（4 帧）、`action/drag_0..2.png`、
`action/fall_0..2.png`。播放序列长度：idle = 4，drag = 3×2 = 6。

## 3. 与 DyberPet 格式的差异

| 项 | DyberPet | 本项目 |
|---|---|---|
| 画布 | 默认 128×128，无上限 | 1~160×180（与程序画布一致） |
| 槽位 | pet_conf 顶层键 | 同左（保持兼容习惯），但校验更严 |
| 附加系统 | 饱食度/好感度分级动作、随机动画表、组件动画、昼夜 | 暂不引入（phase 2+ 按需） |
| 路径 | `res/role/<名>/` | `skins/<包名>/`（本地，gitignore） |

## 4. 版权边界（重要）

1. `skins/` 目录已加入 `.gitignore`：任何放入的皮肤包（含帧图素材）
   **只存在于本地，绝不随仓库提交、发布、分发**；
2. 第三方素材（如 DyberPet 社区 MOD 的画师作品、游戏 IP 二创帧图）版权归
   画师 / IP 方所有，**仅限个人本地自用**；米哈游等官方二创政策允许非商用
   自用，但不允许再分发——因此入库即违规；
3. 分享皮肤包时分享**配置 JSON + 你自制/有授权的帧图**，不得直接转发他人
   素材包；
4. 自制皮肤包建议在包内附 `CREDITS.txt`（素材来源 / 作者 / 授权说明）。

## 5. 校验行为摘要（`core/skin_pack.load_skin_pack`）

- **致命（抛 `SkinPackError`，`issues` 逐条列出）**：目录/配置文件缺失、JSON
  非法、画布越界、`scale`/`act_num`/`frame_refresh` 非法、必需槽位缺失、
  槽位引用未定义动作、动作找不到任何帧图；
- **警告（`SkinPack.warnings`，不阻断）**：未知键、序号断档被忽略的帧；
- 零 Qt / 零 time：可在任何无 GUI 环境加载与测试。

## 6. 渲染通道（phase 2，已接入）

`ui/skin_renderer.py` 负责把加载出的帧图真正画上桌面。要点：

1. **启用方式**：把皮肤包目录放进 `skins/`，启动时
   `build_skin_renderer()` 扫描该目录、加载**首个可用**的包；未放任何包
   （或全部损坏）时自动回落矢量团子猫，无感降级；
2. **槽位映射**（宠物状态 → 皮肤包动作）：拖拽 → `drag`，悬停抚摸 → `patpat`
   （未定义则回落 default），其余 → `default`。`fall` 槽位已定义但当前未接
   自由下落手势（预留）；
3. **帧播放**：`frame_refresh` 秒一帧，`act_num` 循环复用；相位由窗口帧循环
   注入**单调秒数**驱动（零运行期 random，可复现）；
4. **互斥关系**：启用皮肤包后，`paintEvent` 走帧图渲染、不再画矢量团子猫；
   帧图按 `pet_conf` 的 `width`/`height` 铺满、`anchor` 做像素平移修正。

### 验证方式

1. 把某个合法皮肤包解压到 `skins/<包名>/`；
2. 源码运行 `python -m desktop_pet.main`，或重新打包后运行 exe；
3. 宠物应显示为皮肤包帧图动画；拖拽时切到 `drag` 动作；
4. 若仍显示矢量猫，检查 `skins/` 下包结构是否符合第 1 节、以及日志中的
   `已启用皮肤包` / `跳过损坏的皮肤包` 提示。
