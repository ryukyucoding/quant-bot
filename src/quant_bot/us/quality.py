"""獲利品質因子：近四季毛利 ÷ 總資產（Novy-Marx 2013），point-in-time。

毛利優先用公司申報的 GrossProfit；沒有的季度用「營收 − 營業成本」推算；兩者都沒有就不列入。
申報日取組成數字中最晚的那個（全部都公布之後才算得出來）。
"""

from __future__ import annotations

import pandas as pd

from quant_bot.us.fundamentals import QUARTER_DAYS, instant_values, quarterly_values
from quant_bot.us.sec import METRIC_TAGS

COLUMNS = ["end", "filed", "gp_ttm", "assets", "gpa"]


def _metric(rows: pd.DataFrame, metric: str) -> pd.DataFrame:
    return rows[rows["metric"] == metric].drop(columns="metric")


def quarterly_gross_profit(rows: pd.DataFrame) -> pd.DataFrame:
    reported = quarterly_values(_metric(rows, "gross_profit"), METRIC_TAGS["gross_profit"], "gp")
    revenue = quarterly_values(_metric(rows, "revenue"), METRIC_TAGS["revenue"], "rev")
    cost = quarterly_values(_metric(rows, "cost_of_revenue"), METRIC_TAGS["cost_of_revenue"], "cost")
    derived = revenue.merge(cost, on="end", suffixes=("_rev", "_cost"))
    derived = pd.DataFrame(
        {
            "end": derived["end"],
            "filed": derived[["filed_rev", "filed_cost"]].max(axis=1),
            "gp": derived["rev"] - derived["cost"],
        }
    )
    derived = derived[~derived["end"].isin(reported["end"])]
    combined = pd.concat([reported, derived], ignore_index=True)
    combined = combined.astype({"end": "datetime64[ns]", "filed": "datetime64[ns]", "gp": float})
    return combined.sort_values("end").reset_index(drop=True)


def gross_profitability(rows: pd.DataFrame) -> pd.DataFrame:
    gp = quarterly_gross_profit(rows)
    assets = instant_values(_metric(rows, "assets"), "assets")
    if gp.empty or assets.empty:
        return pd.DataFrame(columns=COLUMNS)
    consecutive = gp["end"].diff().dt.days.between(*QUARTER_DAYS).astype(int).rolling(3).sum() == 3
    gp = gp.assign(
        gp_ttm=gp["gp"].rolling(4).sum().where(consecutive),
        filed_ttm=pd.to_datetime(gp["filed"].astype("int64").rolling(4).max()),
    ).dropna(subset=["gp_ttm"])
    merged = gp.merge(assets, on="end", suffixes=("", "_assets"))
    merged = merged[merged["assets"] > 0]
    return pd.DataFrame(
        {
            "end": merged["end"],
            "filed": pd.to_datetime(merged[["filed_ttm", "filed_assets"]].max(axis=1)),
            "gp_ttm": merged["gp_ttm"],
            "assets": merged["assets"],
            "gpa": merged["gp_ttm"] / merged["assets"],
        },
        columns=COLUMNS,
    ).reset_index(drop=True)
