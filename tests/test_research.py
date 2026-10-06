import numpy as np
import pandas as pd

from quant_bot.web.research import render_research

DAYS = pd.bdate_range("2012-01-03", "2014-12-31")


def _result(cagr, sharpe, excess=0.0, won=1, total=2):
    return {"cagr": cagr, "mdd": -0.3, "sharpe": sharpe, "vol": 0.2, "is_cagr": cagr, "oos_cagr": cagr,
            "oos_mdd": -0.1, "excess": excess, "years_won": won, "years_total": total,
            "yearly": {"2012": 0.1, "2013": 0.2, "2014": -0.05}}


def _curves(names):
    rng = np.random.default_rng(1)
    return pd.DataFrame({n: np.cumprod(1 + rng.normal(0.0004, 0.01, len(DAYS))) for n in names}, index=DAYS)


def test_research_page_reports_no_winner_and_escapes():
    results = {"A <x>": _result(0.08, 0.6, -0.05), "B 動能": _result(0.16, 0.8, 0.02, 1, 2),
               "SPY": _result(0.14, 0.9), "RSP": _result(0.12, 0.8, -0.02)}
    html = render_research(results, _curves(results), "https://github.com/u/r", pd.Timestamp("2026-10-06"))
    assert "沒有一組贏過" in html
    assert "B 動能" in html and "+2.0%" in html
    assert "A &lt;x&gt;" in html and "A <x>" not in html
    assert "-2.0%" in html  # RSP vs SPY
    assert 'href="https://github.com/u/r/blob/main/docs/us_strategies_preregistration.md"' in html
    assert "{{" not in html


def test_research_page_counts_sharpe_winners():
    results = {"A": _result(0.2, 1.2, 0.05), "SPY": _result(0.14, 0.9), "RSP": _result(0.12, 0.8, -0.02)}
    html = render_research(results, _curves(results), "", pd.Timestamp("2026-10-06"))
    assert "1 組中只有 1 組贏過" in html
