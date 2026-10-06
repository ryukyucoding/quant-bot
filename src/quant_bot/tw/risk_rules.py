"""新聞與重大訊息的關鍵字風險規則（不使用 AI，免費、可重現、可回測）。

每條規則：在重大訊息主旨／全文或新聞標題中找關鍵字，命中就記一個風險項目並附出處。
- high：任何一條 high 規則命中 → 整檔標為高風險
- watch：只有 watch 命中 → 標為留意
排除字（exclude）用來避開常見誤判，例如會計師因事務所內部輪調而更換、參與子公司增資。
多數規則只看重大訊息「主旨」：全文常有制式欄位（例如「權利受限情形（如質押情形）」）會造成誤判。
v2（2026-10-06）：v1 在第一次實際檢查時，20 檔中有 4 檔誤判（子公司增資、制式欄位），改為只看主旨並排除子公司增資、可轉債轉換發行新股。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from quant_bot.tw.ai_review import AIReview, build_documents
from quant_bot.tw.disclosures import Announcement
from quant_bot.tw.news import NewsItem

METHOD = "keyword-rules-v2"


@dataclass(frozen=True)
class Rule:
    category: str
    severity: str  # high / watch
    pattern: str  # 正規表示式
    exclude: str = ""  # 命中這個就不算
    news: bool = False  # 是否也套用在新聞標題（新聞雜訊多，只開強訊號）
    label: str = ""  # 風險說明；空白時用 category
    full_text: bool = False  # True = 主旨加全文；False = 只看主旨

    def matches(self, text: str) -> bool:
        if not re.search(self.pattern, text):
            return False
        return not (self.exclude and re.search(self.exclude, text))


RULES = (
    Rule("增資或稀釋", "high", r"現金增資|私募|發行新股", r"員工|盈餘轉增資|資本公積轉增資|限制員工權利|子公司|轉投資|認購|收足股款|轉換", label="現金增資、私募或發行新股，可能稀釋股權"),
    Rule("增資或稀釋", "watch", r"可轉換公司債|轉換公司債", label="發行可轉換公司債，未來可能稀釋"),
    Rule("減資", "high", r"減資.{0,6}彌補虧損|彌補虧損.{0,6}減資", label="減資彌補虧損"),
    Rule("財報或會計師疑慮", "high", r"更換會計師事務所|變更會計師事務所|更換.{0,4}事務所", r"內部(組織)?調整|內部輪調", label="更換會計師事務所"),
    Rule("財報或會計師疑慮", "high", r"無法如期|延後公告|延期公告|保留意見|否定意見|無法表示意見|繼續經營.{0,6}(疑慮|重大不確定)", label="財報延遲或會計師意見異常"),
    Rule("訴訟或裁罰", "high", r"檢調|搜索|約談|羈押|起訴|裁罰|罰鍰|處分書", r"不起訴", news=True, full_text=True, label="司法調查、起訴或主管機關裁罰"),
    Rule("訴訟或裁罰", "watch", r"訴訟|仲裁|判決", label="涉及訴訟或仲裁"),
    Rule("停工或災害", "high", r"停工|停產|火災|爆炸|重大災害", news=True, label="停工、停產或災害"),
    Rule("交易限制或下市風險", "high", r"全額交割|變更交易方法|停止買賣|終止上市|終止上櫃|下市|下櫃", news=True, label="交易方式變更或下市櫃風險"),
    Rule("交易限制或下市風險", "high", r"跳票|退票|違約|債務協商|重整|紓困", r"無違約", news=True, label="財務違約或重整"),
    Rule("內部人大量轉讓或質押", "watch", r"設質|質押", label="內部人股票設質"),
    Rule("經營層異動", "watch", r"(董事長|總經理|執行長|財務主管|會計主管|稽核主管).{0,8}(異動|辭|解任|代理)|代理總經理|董事辭", label="經營層或財會主管異動"),
    Rule("其他", "watch", r"澄清", label="公司澄清媒體報導"),
)


def _text(a: Announcement, rule: Rule) -> str:
    return f"{a.subject} {a.detail}" if rule.full_text else a.subject


def review_by_rules(
    code: str, name: str, as_of: pd.Timestamp, announcements: list[Announcement], news: list[NewsItem]
) -> AIReview:
    _, sources = build_documents(announcements, news)
    hits: dict[tuple[str, str], list[str]] = {}
    for i, a in enumerate(announcements, 1):
        for rule in RULES:
            if rule.matches(_text(a, rule)):
                hits.setdefault((rule.category, rule.label or rule.category, rule.severity), []).append(f"A{i}")
    for i, n in enumerate(news, 1):
        for rule in RULES:
            if rule.news and rule.matches(n.title):
                hits.setdefault((rule.category, rule.label or rule.category, rule.severity), []).append(f"N{i}")

    flags = [
        {"category": category, "description": label, "sources": refs[:5]}
        for (category, label, severity), refs in sorted(hits.items(), key=lambda kv: kv[0][2] != "high")
    ]
    severities = {severity for (_, _, severity) in hits}
    severity = "high" if "high" in severities else ("watch" if severities else "none")
    summary = (
        f"近 60 天 {len(announcements)} 則重大訊息、近 30 天 {len(news)} 則新聞；"
        + ("命中：" + "、".join(dict.fromkeys(f["category"] for f in flags)) if flags else "沒有命中風險關鍵字。")
    )
    return AIReview(code, name, f"{as_of:%Y-%m-%d}", summary, severity, flags, sources, model=METHOD)
