"""把 RAGAS 打分结果渲染成单文件 HTML 报告（含四指标雷达/条形图与逐条明细）。

用法：
    python scripts/eval/ragas_report_html.py --scores data/eval/scores_full.json
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS = [
    ("context_precision", "上下文精确度", "相关资料是否排在前面"),
    ("context_recall", "上下文召回率", "参考答案的事实有多少被召回"),
    ("faithfulness", "忠实度", "回答的陈述有多少有资料支撑"),
    ("answer_relevancy", "回答相关性", "回答是否切题"),
]

# 主题色：深色页面 + 蓝绿渐变，与项目前端一致
PALETTE = ["#4f8cff", "#22c3a6", "#f5a524", "#b46bff"]


def bar(name: str, value: float, color: str, hint: str) -> str:
    pct = max(0.0, min(1.0, value)) * 100
    return f"""
    <div class="metric">
      <div class="metric-head">
        <span class="metric-name">{html.escape(name)}</span>
        <span class="metric-value" style="color:{color}">{value:.4f}</span>
      </div>
      <div class="track"><div class="fill" style="width:{pct:.1f}%;background:{color}"></div></div>
      <div class="metric-hint">{html.escape(hint)}</div>
    </div>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", type=Path, default=ROOT / "data" / "eval" / "scores_full.json")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    scores = json.loads(args.scores.read_text(encoding="utf-8"))
    valid = [item for item in scores if all(item.get(key) is not None for key, _, _ in METRICS)]
    if not valid:
        raise SystemExit("没有有效样本")

    summary = {
        key: sum(item[key] for item in valid) / len(valid) for key, _, _ in METRICS
    }
    out = args.out or args.scores.with_name(args.scores.stem.replace("scores", "dashboard") + ".html")

    by_doc: dict[str, list[dict]] = {}
    for item in valid:
        by_doc.setdefault(item.get("doc") or "未知", []).append(item)

    doc_rows = []
    for doc, items in sorted(by_doc.items(), key=lambda kv: -len(kv[1])):
        cells = "".join(
            f"<td class='{'good' if (sum(i[key] for i in items) / len(items)) >= 0.8 else 'warn' if (sum(i[key] for i in items) / len(items)) >= 0.6 else 'bad'}'>"
            f"{sum(i[key] for i in items) / len(items):.3f}</td>"
            for key, _, _ in METRICS
        )
        doc_rows.append(f"<tr><td class='doc'>{html.escape(doc)}</td><td>{len(items)}</td>{cells}</tr>")

    case_rows = []
    for item in sorted(valid, key=lambda x: sum(x[k] for k, _, _ in METRICS)):
        cells = "".join(
            f"<td class='{'good' if item[key] >= 0.8 else 'warn' if item[key] >= 0.6 else 'bad'}'>{item[key]:.3f}</td>"
            for key, _, _ in METRICS
        )
        case_rows.append(
            f"<tr><td class='id'>{html.escape(item['id'])}</td>"
            f"<td class='q'>{html.escape(item['question'])}</td>{cells}</tr>"
        )

    bars = "".join(
        bar(name, summary[key], PALETTE[index % len(PALETTE)], hint)
        for index, (key, name, hint) in enumerate(METRICS)
    )
    avg = sum(summary.values()) / len(summary)
    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RAGAS 评测报告</title>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;padding:32px;background:#0f1420;color:#e8eefc;
       font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
  h1{{font-size:24px;margin:0 0 6px}}
  .sub{{color:#8b9bb8;font-size:13px;margin-bottom:26px}}
  .grid{{display:grid;grid-template-columns:340px 1fr;gap:22px;align-items:start}}
  .card{{background:#161d2d;border:1px solid #232d42;border-radius:14px;padding:20px}}
  .avg{{font-size:44px;font-weight:700;background:linear-gradient(90deg,#4f8cff,#22c3a6);
        -webkit-background-clip:text;background-clip:text;color:transparent;line-height:1.1}}
  .avg-label{{color:#8b9bb8;font-size:12px;letter-spacing:.1em;text-transform:uppercase}}
  .metric{{margin-bottom:18px}}
  .metric-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}}
  .metric-name{{font-size:13px}}
  .metric-value{{font-family:ui-monospace,Consolas,monospace;font-size:16px;font-weight:700}}
  .track{{height:7px;background:#212a3d;border-radius:999px;overflow:hidden}}
  .fill{{height:100%;border-radius:999px;transition:width .8s ease}}
  .metric-hint{{color:#71809c;font-size:11px;margin-top:5px}}
  table{{width:100%;border-collapse:collapse;font-size:12.5px}}
  th{{text-align:left;color:#8b9bb8;font-weight:500;padding:8px 10px;
      border-bottom:1px solid #232d42;font-size:11px;letter-spacing:.04em}}
  td{{padding:8px 10px;border-bottom:1px solid #1b2334;font-family:ui-monospace,Consolas,monospace}}
  td.doc,td.q{{font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
  td.q{{max-width:420px}}
  .good{{color:#22c3a6}} .warn{{color:#f5a524}} .bad{{color:#ff6b81}}
  .id{{color:#4f8cff}}
  h2{{font-size:15px;margin:26px 0 12px;color:#c8d4ea}}
</style></head><body>
<h1>RAGAS 四指标评测</h1>
<div class="sub">样本 {len(valid)} 条 · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 知识库 kb_id=18</div>
<div class="grid">
  <div class="card">
    <div class="avg-label">综合均分</div>
    <div class="avg">{avg:.3f}</div>
    <div style="margin-top:22px">{bars}</div>
  </div>
  <div class="card">
    <h2 style="margin-top:0">按文档分组</h2>
    <table><thead><tr><th>文档</th><th>样本</th>
      {' '.join(f'<th>{n}</th>' for _, n, _ in METRICS)}</tr></thead>
      <tbody>{''.join(doc_rows)}</tbody></table>
  </div>
</div>
<div class="card" style="margin-top:22px">
  <h2 style="margin-top:0">逐条得分（升序，最差的在前）</h2>
  <table><thead><tr><th>用例</th><th>问题</th>
    {' '.join(f'<th>{n}</th>' for _, n, _ in METRICS)}</tr></thead>
    <tbody>{''.join(case_rows)}</tbody></table>
</div>
</body></html>"""
    out.write_text(page, encoding="utf-8")
    print(f"HTML 报告：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
