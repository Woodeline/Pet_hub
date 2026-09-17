"""生成「详情词库人工抽查」HTML 页。

用途：五要素内容由并行 worker 自动生成，机器只能校验结构/上限/零英文残留，
      无法判断释义是否准确、搭配是否真实、例句是否地道。本脚本抽出
      每级若干条渲染成可读卡片，供人工快速抽查。

构建期工具，不进入运行时依赖。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "src" / "desktop_pet" / "data"
WORDS_PATH = DATA_DIR / "jlpt_words.json"
DETAILS_PATH = DATA_DIR / "jlpt_word_details.json"

PER_LEVEL = 6  # 每级抽查条数
LEVEL_ORDER = ["N5", "N4", "N3", "N2", "N1"]
LEVEL_COLOR = {
    "N5": "#0f9d58",
    "N4": "#1a73e8",
    "N3": "#b06000",
    "N2": "#c5221f",
    "N1": "#7b1fa2",
}


def pick_samples(words: list[dict], step_seed: int = 7) -> dict[str, list[dict]]:
    """按等级等距抽样，避免只看到列表开头几条。"""

    by_level: dict[str, list[dict]] = {lv: [] for lv in LEVEL_ORDER}
    for w in words:
        by_level.setdefault(w["level"], []).append(w)

    picked: dict[str, list[dict]] = {}
    for lv in LEVEL_ORDER:
        items = by_level.get(lv, [])
        if not items:
            picked[lv] = []
            continue
        stride = max(1, len(items) // PER_LEVEL)
        sel = [items[(i * stride + step_seed) % len(items)] for i in range(PER_LEVEL)]
        # 去重并保持原序
        seen: set[str] = set()
        uniq = []
        for it in sel:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            uniq.append(it)
        uniq.sort(key=lambda x: items.index(x))
        picked[lv] = uniq
    return picked


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def render_card(word: dict, detail: dict) -> str:
    lv = word["level"]
    color = LEVEL_COLOR.get(lv, "#555")

    meanings = "".join(f"<li>{esc(m)}</li>" for m in detail.get("meaning_zh", []))
    pos = "".join(
        f'<span class="tag">{esc(p)}</span>' for p in detail.get("pos_zh", [])
    )

    collos = detail.get("collocations") or []
    if collos:
        collo_html = "".join(
            f'<li><code>{esc(c.get("phrase", ""))}</code>'
            f'<span class="note">{esc(c.get("note", ""))}</span></li>'
            for c in collos
        )
    else:
        collo_html = '<li class="muted">（该词无常见固定搭配）</li>'

    exs = detail.get("examples") or []
    ex_html = "".join(
        f'<li><div class="jp">{esc(e.get("jp", ""))}</div>'
        f'<div class="zh">{esc(e.get("zh", ""))}</div></li>'
        for e in exs
    )

    return f"""
    <article class="card">
      <header class="card-head">
        <div class="headline">
          <span class="word">{esc(word['word'])}</span>
          <span class="kana">{esc(word['kana'])}</span>
        </div>
        <span class="chip" style="--c:{color}">{esc(lv)}</span>
      </header>

      <div class="field">
        <div class="caption">中文释义</div>
        <ul class="meanings">{meanings}</ul>
      </div>

      <div class="field">
        <div class="caption">词性标注</div>
        <div class="tags">{pos}</div>
      </div>

      <div class="field">
        <div class="caption">常见搭配</div>
        <ul class="collos">{collo_html}</ul>
      </div>

      <div class="field">
        <div class="caption">典型例句</div>
        <ul class="examples">{ex_html}</ul>
      </div>

      <div class="field">
        <div class="caption">语境 / 语气注意</div>
        <p class="usage">{esc(detail.get('usage_note_zh', ''))}</p>
      </div>

      <footer class="card-foot">id: {esc(word['id'])}</footer>
    </article>
    """


def build() -> Path:
    words = json.loads(WORDS_PATH.read_text(encoding="utf-8"))["words"]
    details = json.loads(DETAILS_PATH.read_text(encoding="utf-8"))["details"]

    samples = pick_samples(words)
    total = len(details)
    per_level_count = {lv: sum(1 for w in words if w["level"] == lv) for lv in LEVEL_ORDER}

    sections = []
    for lv in LEVEL_ORDER:
        cards = "".join(
            render_card(w, details[w["id"]])
            for w in samples.get(lv, [])
            if w["id"] in details
        )
        sections.append(
            f"""
            <section class="level-block">
              <h2 style="--c:{LEVEL_COLOR[lv]}">
                <span class="lv">{lv}</span>
                <span class="lv-sub">抽查 {len(samples.get(lv, []))} / {per_level_count[lv]} 条</span>
              </h2>
              <div class="grid">{cards}</div>
            </section>
            """
        )

    stat_rows = "".join(
        f"<tr><td>{lv}</td><td>{per_level_count[lv]}</td><td>{len(samples.get(lv, []))}</td></tr>"
        for lv in LEVEL_ORDER
    )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>日语详情词库 · 人工抽查</title>
<style>
  :root {{
    --bg: #f6f7f9;
    --panel: #ffffff;
    --line: #e3e6ea;
    --ink: #1f2328;
    --ink-2: #57606a;
    --ink-3: #8b949e;
    --accent: #1a73e8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
                 "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 14px;
    line-height: 1.65;
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }}

  .page-head {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 24px 28px;
    margin-bottom: 28px;
  }}
  .page-head h1 {{ margin: 0 0 6px; font-size: 21px; letter-spacing: .2px; }}
  .page-head p {{ margin: 0; color: var(--ink-2); }}
  .kpis {{ display: flex; flex-wrap: wrap; gap: 28px; margin-top: 18px; }}
  .kpi b {{ display: block; font-size: 22px; font-weight: 600; }}
  .kpi span {{ color: var(--ink-3); font-size: 12px; }}
  table {{ border-collapse: collapse; margin-top: 14px; font-size: 13px; }}
  th, td {{ border: 1px solid var(--line); padding: 4px 14px; text-align: left; }}
  th {{ background: #fafbfc; color: var(--ink-2); font-weight: 600; }}

  .level-block {{ margin-top: 34px; }}
  .level-block h2 {{
    display: flex; align-items: baseline; gap: 12px;
    font-size: 16px; margin: 0 0 14px; padding-left: 12px;
    border-left: 4px solid var(--c);
  }}
  .lv {{ color: var(--c); font-weight: 700; letter-spacing: .5px; }}
  .lv-sub {{ color: var(--ink-3); font-size: 12px; font-weight: 400; }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 18px 20px 14px;
    display: flex;
    flex-direction: column;
  }}
  .card-head {{
    display: flex; justify-content: space-between; align-items: flex-start;
    padding-bottom: 12px; border-bottom: 1px dashed var(--line);
  }}
  .headline {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
  .word {{ font-size: 24px; font-weight: 700; letter-spacing: .5px; }}
  .kana {{ color: var(--ink-3); font-size: 13px; }}
  .chip {{
    flex: none; font-size: 11px; font-weight: 700; color: #fff;
    background: var(--c); border-radius: 999px; padding: 2px 9px; letter-spacing: .5px;
  }}

  .field {{ margin-top: 13px; }}
  .caption {{
    font-size: 11px; font-weight: 700; color: var(--ink-3);
    letter-spacing: 1px; margin-bottom: 5px;
  }}
  ul {{ margin: 0; padding-left: 18px; }}
  li {{ margin: 2px 0; }}
  .meanings li::marker {{ color: var(--accent); }}

  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .tag {{
    background: #eef2f7; color: #33404d; border-radius: 6px;
    padding: 1px 8px; font-size: 12px;
  }}

  .collos {{ list-style: none; padding-left: 0; }}
  .collos li {{ display: flex; gap: 8px; align-items: baseline; }}
  .collos code {{
    background: #f3f5f8; border-radius: 5px; padding: 1px 7px;
    font-family: "SFMono-Regular", Consolas, monospace; font-size: 12.5px; color: #0b4f9e;
  }}
  .collos .note {{ color: var(--ink-2); font-size: 12.5px; }}

  .examples {{ list-style: none; padding-left: 0; }}
  .examples li {{ padding: 6px 0 6px 12px; border-left: 2px solid #e8eef7; margin-bottom: 4px; }}
  .examples .jp {{ font-weight: 600; }}
  .examples .zh {{ color: var(--ink-2); font-size: 13px; }}

  .usage {{
    margin: 0; background: #fbf7ec; border: 1px solid #f0e4c8;
    border-radius: 8px; padding: 8px 11px; font-size: 13px; color: #57492c;
  }}
  .muted {{ color: var(--ink-3); }}

  .card-foot {{
    margin-top: 14px; padding-top: 8px; border-top: 1px solid var(--line);
    color: var(--ink-3); font-size: 11px; font-family: Consolas, monospace;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page-head">
    <h1>日语学习详情词库 · 人工抽查表</h1>
    <p>五要素内容由并行生成，机器仅能校验<b>结构 / 展示上限 / 零英文残留</b>；
       释义准确度、搭配真实性、例句地道度需人工判断。以下为等距抽样。</p>
    <div class="kpis">
      <div class="kpi"><b>{total}</b><span>词条总数</span></div>
      <div class="kpi"><b>{len(LEVEL_ORDER)}</b><span>等级数</span></div>
      <div class="kpi"><b>{sum(len(v) for v in samples.values())}</b><span>本次抽查条数</span></div>
    </div>
    <table>
      <tr><th>等级</th><th>词库条数</th><th>抽查条数</th></tr>
      {stat_rows}
    </table>
  </div>
  {''.join(sections)}
</div>
</body>
</html>
"""

    out = REPO_ROOT / "docs" / "word-detail-sample.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out


if __name__ == "__main__":
    path = build()
    print(f"written: {path}")
