"""美股因子研究：一次跑完預先登記的五組策略（docs/us_strategies_preregistration.md）加上營收策略，全部列出。

輸出 reports/us_factor_research.json（指標）與 data/us/research_curves.parquet（淨值曲線），並在終端機印出摘要。
規則已在回測前寫定，這支腳本只重跑同一組規則（資料更新時數字會小幅變動），不調整參數。
"""
import json
import logging
from pathlib import Path

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.backtest import run_backtest
from quant_bot.common.costs import us_stock_costs
from quant_bot.common.portfolio import summarize_window
from quant_bot.us import pipeline as us
from quant_bot.us.factor_strategies import FACTOR_STRATEGIES, FactorInputs, build_factor_targets

ROOT = Path(__file__).resolve().parents[1]
OOS_START = us.IN_SAMPLE_END + pd.Timedelta(days=1)


def evaluate(equity: pd.Series, market: pd.Series) -> dict:
    full, is_, oos = (summarize_window(equity, s, e) for s, e in ((None, None), (None, us.IN_SAMPLE_END), (OOS_START, None)))
    rel = metrics.relative_to(equity, market)
    return {
        "cagr": full["cagr"], "mdd": full["max_drawdown"], "sharpe": full["sharpe"], "vol": full["volatility"],
        "is_cagr": is_["cagr"], "oos_cagr": oos["cagr"], "oos_mdd": oos["max_drawdown"], "oos_sharpe": oos["sharpe"],
        "excess": rel["excess_cagr"], "years_won": rel["years_won"], "years_total": rel["years_total"],
        "yearly": {str(k): v for k, v in metrics.calendar_year_returns(equity).items()},
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    inputs = us.load_inputs(ROOT)
    factor_inputs = FactorInputs(inputs.panel, inputs.history, pd.read_parquet(ROOT / "data" / "us" / "quality.parquet"))
    costs = us_stock_costs()

    curves: dict[str, pd.Series] = {}
    for config in FACTOR_STRATEGIES:
        targets = build_factor_targets(factor_inputs, config, us.BACKTEST_START)
        curves[config.name] = run_backtest(inputs.panel.adj_close, targets, costs).equity
        logging.info("done %s", config.name)
    revenue = next(r for r in us.run_all(inputs) if r.config == us.PRIMARY)
    curves["營收策略（先前）"] = revenue.result.equity

    start = min(c.index[0] for c in curves.values())
    benchmarks = {b.short: b.equity for b in us.load_benchmarks(inputs, start)}
    market = benchmarks["大盤"]
    results = {name: evaluate(eq, market) for name, eq in {**curves, "SPY": market, "RSP": benchmarks["RSP"]}.items()}

    all_curves = pd.DataFrame({**curves, "SPY": market, "RSP": benchmarks["RSP"]})
    all_curves.to_parquet(ROOT / "data" / "us" / "research_curves.parquet")
    out = ROOT / "reports" / "us_factor_research.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'策略':22s} {'年化':>7s} {'回撤':>7s} {'Sharpe':>6s} {'設計期':>7s} {'驗證期':>7s} {'驗證回撤':>8s} {'超額':>6s} 勝年")
    for name, r in results.items():
        print(
            f"{name:22s} {r['cagr']:7.1%} {r['mdd']:7.1%} {r['sharpe']:6.2f} {r['is_cagr']:7.1%} "
            f"{r['oos_cagr']:7.1%} {r['oos_mdd']:8.1%} {r['excess']:+6.1%} {r['years_won']}/{r['years_total']}"
        )
    yearly = pd.DataFrame({name: r["yearly"] for name, r in results.items()})
    print((yearly * 100).round(1).to_string())


if __name__ == "__main__":
    main()
