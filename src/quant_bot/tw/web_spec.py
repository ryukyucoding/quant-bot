"""台股報告頁的文字與欄位。"""

from __future__ import annotations

import pandas as pd

from quant_bot.tw.pipeline import IN_SAMPLE_END, PRIMARY
from quant_bot.web.spec import MarketSpec, number_column, pct_column, text_column


def _next_update(as_of: pd.Timestamp) -> tuple[pd.Timestamp, str]:
    return (as_of.to_period("M") + 1).to_timestamp() + pd.Timedelta(days=10), "次月 10 日營收公布後"


NOTES = """
<li><b>倖存者偏差（影響最大）：</b>公開資訊觀測站的歷史營收彙總表是近期重新產生的，只列出「現在還存在」的公司；Yahoo Finance 也沒有下市股票的價格。所以回測只在「活下來的公司」裡選股，所有策略的報酬都偏高。比較公平的看法是：主策略有沒有贏過「合格股票全部等權重」這組（兩者偏差相同），而不是只看有沒有贏大盤。</li>
<li><b>營收修正：</b>月營收以公開資訊觀測站目前的版本為準，少數公司事後更正的數字，在當時不一定看得到。</li>
<li><b>成交假設：</b>選股隔天以收盤價成交（延遲 5 天下單，年化報酬約少 1 個百分點），每邊另計 0.1% 滑價；手續費 0.1425% 未打折，賣出加計 0.3% 證交稅。小型股實際滑價可能更大。</li>
<li><b>大盤基準：</b>用證交所「發行量加權股價報酬指數」，含現金股利再投入。一般看到的加權指數不含股利，每年少算約 3–4%，拿它比會高估策略。策略也會選到上櫃股，所以這裡的大盤只涵蓋上市股票。</li>
<li><b>篩選門檻：</b>股價 ≥ 10 元、近 60 日平均成交金額 ≥ 3,000 萬、近三月營收 ≥ 3 億、排除金融保險業。</li>
<li><b>不是投資建議：</b>這份報告是研究工具，過去的回測績效不代表未來報酬。下單前請自行判斷。</li>
"""

TW_SPEC = MarketSpec(
    key="tw",
    label="台股",
    name="台股月營收選股",
    site_dir="",
    eyebrow="台股月營收選股 · 月報",
    cover_title=lambda period: f"{period.year} 年 {period.month} 月營收選股",
    next_update=_next_update,
    primary_name=PRIMARY.name,
    strategy_short=("全部等權", "營收年增", "營收創高", "主策略"),
    in_sample_end=IN_SAMPLE_END,
    method_html=(
        f"主策略「{PRIMARY.name}」：在流動性、股價與營收規模都合格的股票中，挑出營收創 12 個月新高、"
        f"連續三個月年增、股價站上 120 日均線者，依近三月營收年增率排序取前 {PRIMARY.top_n} 名，等權重持有。"
    ),
    pick_columns=(
        text_column("<th>產業</th>", "industry"),
        pct_column('<th class="num">近三月<br>營收年增</th>', "yoy_3"),
        pct_column('<th class="num">單月<br>營收年增</th>', "yoy_1"),
        number_column('<th class="num">近三月營收<br>（億元）</th>', "rev_3m", digits=1, scale=1e5),
        number_column('<th class="num">收盤價</th>', "close", digits=1),
    ),
    backtest_intro_html=(
        "回測期間 {BT_START} 起，每月營收公布後的第一個交易日（11 日前後）收盤後選股、隔一個交易日以收盤價換股，"
        "已扣除手續費、證交稅與滑價。{IS_END} 年以前為「設計期」，{OOS_START} 年起為「驗證期」，規則在驗證期沒有再調整過。"
    ),
    market_note="大盤 = 加權報酬指數，含現金股利",
    notes_html=NOTES,
    sources="公開資訊觀測站月營收彙總表、臺灣證券交易所發行量加權股價報酬指數、Yahoo Finance",
    period_header="營收月份",
    first_publish_note="還沒有正式發布的名單，第一期會在下一次營收公布後（每月 11 日）發布。",
    subscribe_note="每月 11 日營收公布後推播",
    growth_field="yoy_3",
    growth_label="近三月營收年增",
)
