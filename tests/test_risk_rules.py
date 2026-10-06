import pandas as pd
import pytest

from quant_bot.tw.disclosures import Announcement
from quant_bot.tw.news import NewsItem
from quant_bot.tw.risk_rules import RULES, review_by_rules

AS_OF = pd.Timestamp("2026-10-06")


def _ann(subject: str, detail: str = "") -> Announcement:
    return Announcement("1234", "2026-09-01", "17:00:00", subject, "1", "20260901", "170000", "sii", detail)


@pytest.mark.parametrize(
    ("subject", "severity", "category"),
    [
        ("董事會決議辦理現金增資發行新股", "high", "增資或稀釋"),
        ("本公司更換會計師事務所", "high", "財報或會計師疑慮"),
        ("本公司股票將變更交易方法為全額交割", "high", "交易限制或下市風險"),
        ("本公司董事長異動", "watch", "經營層異動"),
        ("董事會決議發行國內第三次無擔保轉換公司債", "watch", "增資或稀釋"),
        ("本公司受邀參加法人說明會", "none", None),
        ("公告本公司8月營收", "none", None),
    ],
)
def test_announcement_rules(subject, severity, category):
    review = review_by_rules("1234", "測試", AS_OF, [_ann(subject)], [])
    assert review.severity == severity
    if category:
        assert category in {f["category"] for f in review.flags}


@pytest.mark.parametrize(
    "subject",
    ["簽證會計師因會計師事務所內部輪調而更換", "董事會決議員工酬勞發行新股", "本公司不起訴處分確定"],
)
def test_common_false_positives_are_excluded(subject):
    assert review_by_rules("1234", "測試", AS_OF, [_ann(subject)], []).severity == "none"


def test_news_only_triggers_strong_rules():
    news = [NewsItem("測試公司遭檢調搜索", "某報", "2026-09-10", "https://a"),
            NewsItem("測試公司董事長異動", "某報", "2026-09-11", "https://b")]
    review = review_by_rules("1234", "測試", AS_OF, [], news)
    assert review.severity == "high"
    assert review.flags[0]["sources"] == ["N1"]


def test_high_flags_are_listed_first_and_summary_counts():
    review = review_by_rules("1234", "測試", AS_OF, [_ann("董事長辭職"), _ann("辦理私募")], [])
    assert review.flags[0]["category"] == "增資或稀釋"
    assert review.summary.startswith("近 60 天 2 則重大訊息")


def test_every_rule_has_a_category_and_valid_severity():
    assert all(r.severity in ("high", "watch") and r.category for r in RULES)


@pytest.mark.parametrize(
    ("subject", "detail"),
    [
        ("本公司參與認購子公司現金增資案", ""),
        ("本公司間接以現金增資子公司QCG", ""),
        ("代重要子公司公告現金增資收足股款暨增資基準日", ""),
        ("本公司取得有價證券", "權利受限情形（如質押情形）：無"),
        ("公告本公司董事會決議召開股東臨時會", "討論事項：擬辦理私募發行新股案"),
    ],
)
def test_v1_false_positives_are_fixed(subject, detail):
    assert review_by_rules("1234", "測試", AS_OF, [_ann(subject, detail)], []).severity == "none"


def test_investigation_rule_still_reads_full_text():
    ann = _ann("本公司更換簽證會計師", "配合檢調單位調查出具內部控制建議書")
    assert review_by_rules("1234", "測試", AS_OF, [ann], []).severity == "high"


def test_convertible_conversion_is_watch_not_high():
    ann = _ann("公告本公司國內第二次無擔保轉換公司債轉換普通股之發行新股")
    assert review_by_rules("1234", "測試", AS_OF, [ann], []).severity == "watch"
