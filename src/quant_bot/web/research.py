"""美股研究結果頁：預先登記的策略全部列出，與 SPY、RSP 比較。數字全部由研究結果計算，不寫死在文字裡。"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.svg_chart import Line, line_chart
from quant_bot.web.report import STYLE, TEMPLATES
from quant_bot.web.spec import num, pct, tone

TEMPLATE = TEMPLATES / "research.html"
MARKET, EQUAL = "SPY", "RSP"
STRATEGY_CLASSES = ("s-r1", "s-r2", "s-r3", "s-r4", "s-r5", "s-r6")
PREREG_PATH = "blob/main/docs/us_strategies_preregistration.md"


def _rows(results: dict) -> str:
    rows = []
    classes = dict(zip([k for k in results if k not in (MARKET, EQUAL)], STRATEGY_CLASSES))
    classes |= {MARKET: "s-market", EQUAL: "s-bench"}
    for name, r in results.items():
        is_market = name == MARKET
        label = "S&P 500（SPY，含息）" if is_market else ("S&P 500 等權重（RSP）" if name == EQUAL else name)
        record = "—" if is_market else f'{r["years_won"]} / {r["years_total"]}'
        excess = float("nan") if is_market else r["excess"]
        rows.append(
            f'<tr class="{"market" if is_market else ""}"><th scope="row"><span class="swatch {classes[name]}"></span>{escape(label)}</th>'
            f'<td class="num {tone(r["cagr"])}">{pct(r["cagr"])}</td>'
            f'<td class="num down-only">{pct(r["mdd"], signed=False)}</td>'
            f'<td class="num">{num(r["sharpe"])}</td>'
            f'<td class="num {tone(r["oos_cagr"])}">{pct(r["oos_cagr"])}</td>'
            f'<td class="num down-only">{pct(r["oos_mdd"], signed=False)}</td>'
            f'<td class="num {tone(excess)} excess">{pct(excess)}</td>'
            f'<td class="num">{record}</td></tr>'
        )
    return "".join(rows)


def _yearly(results: dict) -> str:
    names = list(results)
    yearly = pd.DataFrame({n: results[n]["yearly"] for n in names})
    head = "".join(f'<th scope="col" class="num">{escape(n.split(" ")[0] if n not in (MARKET, EQUAL) else n)}</th>' for n in names)
    body = []
    for year, row in yearly.iterrows():
        partial = " *" if year in (yearly.index[0], yearly.index[-1]) else ""
        cells = "".join(f'<td class="num {tone(row[n])}">{pct(row[n])}</td>' for n in names)
        body.append(f'<tr><th scope="row" class="num">{year}{partial}</th>{cells}</tr>')
    return f'<table class="yearly"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _chart(curves: pd.DataFrame) -> tuple[str, str]:
    strategies = [c for c in curves.columns if c not in (MARKET, EQUAL)]
    lines = [Line(name, curves[name].dropna(), STRATEGY_CLASSES[i]) for i, name in enumerate(strategies)]
    lines += [Line("S&P 500 等權重（RSP）", curves[EQUAL].dropna(), "s-bench"), Line("S&P 500（SPY）", curves[MARKET].dropna(), "s-market")]
    legend = "".join(f'<li><span class="swatch {ln.css_class}"></span>{escape(ln.label)}</li>' for ln in lines)
    return line_chart(lines, title="累積淨值（對數刻度）"), legend


def _facts(results: dict) -> dict[str, str]:
    strategies = {k: v for k, v in results.items() if k not in (MARKET, EQUAL)}
    best = max(strategies.items(), key=lambda kv: kv[1]["excess"])
    spy, rsp = results[MARKET], results[EQUAL]
    beat_sharpe = sum(v["sharpe"] > spy["sharpe"] for v in strategies.values())
    return {
        "{{N_STRATEGIES}}": str(len(strategies)),
        "{{SHARPE_VERDICT}}": (
            "算上風險（Sharpe）之後，沒有一組贏過直接買 S&amp;P 500。"
            if beat_sharpe == 0
            else f"算上風險（Sharpe）之後，{len(strategies)} 組中只有 {beat_sharpe} 組贏過直接買 S&amp;P 500。"
        ),
        "{{SPY_CAGR}}": pct(spy["cagr"], signed=False),
        "{{SPY_SHARPE}}": num(spy["sharpe"]),
        "{{BEST_NAME}}": escape(best[0]),
        "{{BEST_EXCESS}}": pct(best[1]["excess"]),
        "{{BEST_WON}}": f'{best[1]["years_won"]} / {best[1]["years_total"]}',
        "{{RSP_GAP}}": pct(rsp["cagr"] - spy["cagr"]),
    }


def render_research(results: dict, curves: pd.DataFrame, github_url: str, generated_at: pd.Timestamp) -> str:
    chart, legend = _chart(curves)
    start, end = curves.dropna(how="all").index[[0, -1]]
    prereg = f'<a href="{escape(github_url.rstrip("/"))}/{PREREG_PATH}" rel="noopener">預先登記文件</a>' if github_url else "預先登記文件"
    replacements = {
        "{{STYLE}}": STYLE.read_text(encoding="utf-8"),
        "{{ROWS}}": _rows(results),
        "{{YEARLY}}": _yearly(results),
        "{{EQUITY_SVG}}": chart,
        "{{LEGEND}}": legend,
        "{{PERIOD}}": f"{start:%Y-%m} 至 {end:%Y-%m}",
        "{{PREREG_LINK}}": prereg,
        "{{GENERATED}}": f"{generated_at:%Y-%m-%d}",
        **_facts(results),
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


def load_results(root: Path) -> tuple[dict, pd.DataFrame]:
    import json

    results = json.loads((root / "reports" / "us_factor_research.json").read_text(encoding="utf-8"))
    curves = pd.read_parquet(root / "data" / "us" / "research_curves.parquet")
    return results, curves
