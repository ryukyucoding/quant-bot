"""交易成本模型：以「成交金額比例」表示買進與賣出的單邊成本。"""

from __future__ import annotations

from dataclasses import dataclass

TW_BROKER_FEE = 0.001425  # 券商手續費（未打折）
TW_TRANSACTION_TAX = 0.003  # 證交稅，賣出時收
DEFAULT_SLIPPAGE = 0.001  # 每邊假設 0.1% 滑價


@dataclass(frozen=True)
class CostModel:
    buy_rate: float
    sell_rate: float

    def __post_init__(self) -> None:
        if not (0 <= self.buy_rate < 0.1 and 0 <= self.sell_rate < 0.1):
            raise ValueError("cost rates must be within [0, 0.1)")

    def cost_of(self, bought: float, sold: float) -> float:
        """bought / sold 為佔總資產的比例，回傳成本佔總資產比例。"""
        return bought * self.buy_rate + sold * self.sell_rate


def tw_stock_costs(fee_discount: float = 1.0, slippage: float = DEFAULT_SLIPPAGE) -> CostModel:
    """台股現股：手續費（可打折）+ 賣出證交稅 + 雙邊滑價。"""
    if not 0 < fee_discount <= 1:
        raise ValueError("fee_discount must be in (0, 1]")
    fee = TW_BROKER_FEE * fee_discount
    return CostModel(buy_rate=fee + slippage, sell_rate=fee + TW_TRANSACTION_TAX + slippage)


ZERO_COST = CostModel(0.0, 0.0)


US_COMMISSION = 0.001  # 複委託常見折扣後約 0.1%；IBKR 等海外券商更低
US_SEC_FEE = 0.0000278  # 賣出時的 SEC 規費
US_SLIPPAGE = 0.0005  # S&P 500 大型股流動性好


def us_stock_costs(commission: float = US_COMMISSION, slippage: float = US_SLIPPAGE) -> CostModel:
    """美股（台灣投資人透過複委託）：手續費 + 雙邊滑價，賣出加 SEC 規費。"""
    return CostModel(buy_rate=commission + slippage, sell_rate=commission + slippage + US_SEC_FEE)
