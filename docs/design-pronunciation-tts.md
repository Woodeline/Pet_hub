# design-pronunciation-tts —— 单词发音功能（2026-10-01）

## 需求与决策

详情窗 / 生词本卡片的喇叭原为置灰占位（点击无响应）。本次点亮：

- **发音来源**：Google 翻译 TTS（非官方、免费无 key），`tl=ja`，文本优先词头表记、缺省回落假名。
- **生效范围**：详情窗 + 生词本卡片两处喇叭。
- **触发**：仅手动点击喇叭，不自动播放。

## 架构（复用详情功能三段式范式）

```
SpeakerButton(QLabel 派生，三态：normal/loading/error，只发 clicked)
        │ clicked
        ▼
PronunciationController(QObject，主线程，两窗共用单例)
  ├─ 缓存快路：AudioCacheStore.load 命中 → 直接播（不发请求）
  ├─ 未命中：PronunciationWorker(QRunnable, 后台线程)
  │    查缓存 → GoogleTTSClient.fetch(urllib, 同步) → AudioCacheStore.save(原子写) → succeeded/failed
  └─ PronunciationPlayer.play（打断式串行播放）
状态经 state_changed(key, state, message) 广播；key = spoken_text(word, kana)，
两个窗口各自按当前词条的 key 过滤刷新喇叭（详情窗另有 item_id 守卫的同款思路）。
```

- 缓存：`%APPDATA%\desktop-pet\audio_cache\<sha1(text)>.mp3`，无 JSON 索引（文件系统即索引）。
- 在途去重：同 key busy 集合；错误态解除 busy 保证可重试。
- 播放失败（缓存文件损坏）→ controller 删缓存 + 广播 error，下次点击重取。
- 抓取成功但落盘失败（只读盘）→ 退化为系统临时文件播放，本次不缓存。

## 关键替代决策：winmm/MCI 替代 QtMultimedia

计划阶段选了 `PySide6.QtMultimedia`，实施时发现**运行时（workbuddy env）只装
`PySide6_Essentials`**，QtMultimedia 属于 `PySide6_Addons` 轮子。两个选项：

1. 补装 Addons：需改共享运行时环境 + PyInstaller onefile 体积 +约几十 MB；
2. **改用标准库 `ctypes` 调 `winmm.mciSendStringW`**（`open "...mp3" type mpegvideo alias x` + `play`）：零新增依赖、打包体积不变，`mpegvideo` 打不开时回落按文件关联打开。

选 2（本项目为 Windows 专用应用）。代价：MCI 无完成回调（不需要）；错误为同步错误码
（open/play 任一非 0 → `play_failed` 信号）。

## 追加修正：发音源改为「有道主源 + Google 回退」（2026-10-01 用户真机反馈后）

用户真机点击无声音，日志定位为 **`translate.google.com` 在国内网络不可达**
（`urlopen timed out`，MCI 播放链路本机实测 open/play 均 rc=0 正常）。实测定参：

- 有道词典发音 `dict.youdao.com/dictvoice?audio=<text>&le=ja`：**国内可达**，返回
  `audio/mpeg` 无需鉴权（私=2.1KB、明後日=31.2KB，md5 随词变化，MP3 帧头 `ff f3`）；
- Google 翻译 TTS：保留为海外回退源（仍需浏览器 UA）；
- `TTSClient.fetch` 按源序尝试，单源网络/解析失败即换下一个，全败抛最后异常；
  单源超时 6s（两源全超时最坏约 12s 后喇叭进错误态）。

端到端实测（真实网络 + 真实 client + 缓存落盘）通过。

## 追加修正 2：发音输入优先假名（纠错机制，2026-10-01 用户反馈「明後日」发音不符）

**根因**：明後日 = あさって 是熟字训（不规则读法），TTS 拿汉字串按字面拼读必错。
**纠错机制**：`spoken_text` 翻转为**优先假名**——假名即读音本身，喂 TTS 永不出错；
仅当假名缺失或混入非假名字符（`_is_pure_kana` 数据卫生防线）才回落词头。
缓存键 = 发音文本，翻转后旧错误缓存天然不命中。全量核查（7738 条）：
7728 条走假名，10 条外置词库数据瑕疵（多读音斜杠/括注/乱码）回退词头。

**不做**离线「听音比对」自动校验：无 ASR，成本与收益不成比例；假名优先已从
根源消灭该类错误。

## 线程边界

`core/tts_client.py`、`core/audio_cache.py` 禁 Qt 禁 time；线程只在
`ui/pronunciation_worker.py`（与 `word_detail_worker` 同范式，run() 绝不裸抛）。

## 测试

`tests/test_tts_client.py`（mock urlopen：URL/UA/重试/异常分类 + worker 四态）、
`tests/test_audio_cache.py`（往返/原子/容错）、`tests/test_speaker_button.py`
（按钮三态 + controller 编排 fake player/pool + 两窗接线）。offscreen，不真实出声。

## 真机验收清单（人工）

- 点击详情窗喇叭 → 出声；再点同一词 → 秒播（缓存命中）。
- 断网点击新词 → 喇叭置灰 + tooltip「发音获取失败」，详情窗底部状态行提示；恢复网络重试成功。
- 生词本卡片喇叭同上；连点两个不同词 → 只出后一个的声音。
- `%APPDATA%\desktop-pet\audio_cache\` 出现 `*.mp3`。
