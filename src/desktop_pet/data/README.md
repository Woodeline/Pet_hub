# 内置 JLPT 词库编写规范（`data/`）

本目录存放**随包分发的只读词库**。词库离线可用、零外部依赖，仅以 JSON 文本形式存在
（JSON 不受「零外部图片素材」限制）。运行时由 `desktop_pet.core.paths.word_bank_path()`
定位、`desktop_pet.core.vocabulary.WordBank.load()` 容错加载。

## 1. 文件

| 文件 | 说明 |
| --- | --- |
| `jlpt_words.json` | 唯一词库文件，UTF-8 编码，`version: 1`。 |

## 2. JSON schema

```json
{
  "version": 1,
  "words": [
    {
      "id": "n5-0001",
      "level": "N5",
      "word": "私",
      "kana": "わたし",
      "romaji": "watashi",
      "translation": "我",
      "meaning": "第一人称代词，通用/正式说法"
    }
  ]
}
```

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| `id` | string | ✅ | **全局唯一**。格式 `n<级别数字>-<四位序号>`，如 `n5-0001`、`n1-0100`。去重键。 |
| `level` | string | ✅ | 取值必须是 `"N5" / "N4" / "N3" / "N2" / "N1"`（`core.constants.JP_LEVELS`）。 |
| `word` | string | ✅ | 日语单词表记（汉字 / 平假名 / 片假名，非空）。 |
| `kana` | string | ✅ | **假名读音**，要求**全为平假名**（可含长音符 `ー`）；**不得含汉字、罗马字或空格**。 |
| `romaji` | string | ⬜（可省略） | 罗马音（P2 预留，**存而不显**：MVP 泡泡与生词本均不展示）。 |
| `translation` | string | ✅ | 简短中文对应词（如「我」「吃」）。 |
| `meaning` | string | ✅ | 中文词性 / 用法说明（如「动词（五段），交谈」）。 |

> 说明：`WordBank.load` 会**逐条**校验——任一必填字段缺失 / 非字符串 / 空串，
> 或 `level` 不在 `JP_LEVELS`，该条即被跳过（记 warning）。因此词库必须保证无非法记录，
> 否则会出现「加载后条数 < 原始条数」的静默丢弃。

## 3. 编写要求

1. **每级 ≥ 100 词**（当前为 N5~N1 各 100 条，共 500 条）。
2. `id` 全局唯一、格式正确（`n5-0001` 起，逐级递增）。
3. `kana` 读音必须**准确**——这是学习者最依赖的字段。
4. `level` 必须与 JLPT 难度相符（N5 最易 → N1 最难）。
5. `translation` 是简短中文对应词；`meaning` 是中文词性 / 用法说明。
6. **不得**使用占位符或重复内容凑数。

## 4. 如何扩充

1. 在 `words` 数组**末尾追加**对象，`id` 序号在对应级别上递增（不要复用已删 id）。
2. 保持文件为合法 JSON（UTF-8、逗号正确）。
3. 运行仓库根的自检脚本核对（该脚本以下划线开头、已被 `.gitignore` 忽略）：

   ```bash
   PYTHONPATH=src python _check_wordbank.py
   ```

   它会校验：各等级词数 ≥ 100、`id` 唯一且格式正确、必填字段非空且为 str、
   `level ∈ JP_LEVELS`、`kana` 只含假名/长音符、`word` 非空，以及
   `WordBank.load()` 后 `size()` 等于原始条数（即无记录被静默丢弃）。
