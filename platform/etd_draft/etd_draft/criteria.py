"""GRADE EtD フレームワーク（Minds 2020 RC-7, Individual perspective）の判断基準定義。

ここは決定論的なマスタデータ。LLM はこの選択肢からしか判断を選べず、
選択肢外の文字列は verify で reject される。
"""

from __future__ import annotations

from dataclasses import dataclass, field

NO_INFO = "情報なし"
TO_BE_JUDGED = "要判断（委員）"

# 共通の判断選択肢セット
YES_NO_5 = ["いいえ", "おそらくいいえ", "不確実", "おそらくはい", "はい", "さまざま"]
MAGNITUDE_4 = ["わずか", "小さい", "中程度", "大きい", "さまざま", "わからない"]
CERTAINTY_4 = ["⊕◯◯◯（非常に低）", "⊕⊕◯◯（低）", "⊕⊕⊕◯（中）", "⊕⊕⊕⊕（高）", "採用研究なし"]
VALUES_3 = [
    "重要な不確実性またはばらつきあり",
    "重要な不確実性またはばらつきの可能性あり",
    "重要な不確実性またはばらつきはおそらくなし",
    "重要な不確実性またはばらつきなし",
]
BALANCE_5 = [
    "比較対照を支持",
    "おそらく比較対照を支持",
    "介入も比較対照も支持しない",
    "おそらく介入を支持",
    "介入を支持",
    "さまざま",
    "わからない",
]
RESOURCE_5 = [
    "大きなコスト",
    "中程度のコスト",
    "無視できるコストと節約",
    "中程度の節約",
    "大きな節約",
    "さまざま",
    "わからない",
]
EQUITY_5 = [
    "低下する",
    "おそらく低下する",
    "おそらく影響しない",
    "おそらく向上する",
    "向上する",
    "さまざま",
    "わからない",
]


@dataclass(frozen=True)
class Criterion:
    id: str
    order: int
    label_ja: str
    question_ja: str
    options: list[str]
    # 元GL本文から「候補エビデンス」を機械的に拾うためのキーワード（決定論的ルーティング用）
    keywords: list[str] = field(default_factory=list)
    # 旧GLには通常記載されず、委員の追加考慮に委ねられることが多い項目か
    usually_absent_in_gl: bool = False


CRITERIA: list[Criterion] = [
    Criterion(
        id="problem",
        order=1,
        label_ja="問題の優先度",
        question_ja="この問題は優先事項か？",
        options=YES_NO_5,
        keywords=["頻度", "発症率", "有病率", "罹患", "負担", "QOL", "生活の質", "重要な", "問題", "減量", "中止", "後遺", "遷延"],
    ),
    Criterion(
        id="desirable_effects",
        order=2,
        label_ja="望ましい効果",
        question_ja="期待される望ましい効果はどの程度大きいか？",
        options=MAGNITUDE_4,
        keywords=["有効", "改善", "軽減", "低下", "減少", "予防", "効果", "有意", "リスク比", "オッズ比", "差", "RR", "OR", "MD", "SMD", "HR"],
    ),
    Criterion(
        id="undesirable_effects",
        order=3,
        label_ja="望ましくない効果",
        question_ja="期待される望ましくない効果はどの程度大きいか？",
        options=MAGNITUDE_4,
        keywords=["有害", "副作用", "害", "有害事象", "安全性", "悪化", "増加", "合併症", "凍傷", "疼痛", "不快", "離脱", "中止"],
    ),
    Criterion(
        id="certainty",
        order=4,
        label_ja="エビデンスの確実性",
        question_ja="効果に関するエビデンス全体の確実性はどの程度か？",
        options=CERTAINTY_4,
        keywords=["エビデンス", "確実性", "質", "バイアス", "非一貫性", "非直接性", "不精確", "出版バイアス", "⊕", "RCT", "ランダム化", "メタアナリシス", "システマティック", "異質性"],
    ),
    Criterion(
        id="values",
        order=5,
        label_ja="価値観",
        question_ja="主要アウトカムを人々がどの程度重視するかについて、重要な不確実性やばらつきがあるか？",
        options=VALUES_3,
        keywords=["価値観", "好み", "希望", "選好", "重視", "患者の", "患者が", "意向", "満足", "PRO", "患者報告"],
        usually_absent_in_gl=True,
    ),
    Criterion(
        id="balance",
        order=6,
        label_ja="効果のバランス",
        question_ja="望ましい効果と望ましくない効果のバランスは、介入と比較対照のどちらを支持するか？",
        options=BALANCE_5,
        keywords=["バランス", "上回", "下回", "益", "害", "総合", "勘案", "考慮すると", "推奨する", "提案する", "推奨しない", "提案しない"],
    ),
    Criterion(
        id="resources",
        order=7,
        label_ja="必要資源量",
        question_ja="必要な資源（コスト）はどの程度大きいか？",
        options=RESOURCE_5,
        keywords=["費用", "コスト", "薬価", "価格", "円", "保険", "適用外", "自費", "資源", "人員", "時間", "機器", "医療経済"],
        usually_absent_in_gl=True,
    ),
    Criterion(
        id="cost_effectiveness",
        order=8,
        label_ja="費用対効果",
        question_ja="費用対効果は介入と比較対照のどちらを支持するか？",
        options=BALANCE_5,
        keywords=["費用対効果", "費用効果", "ICER", "QALY", "経済評価", "医療経済"],
        usually_absent_in_gl=True,
    ),
    Criterion(
        id="equity",
        order=9,
        label_ja="公平性",
        question_ja="健康の公平性にどのような影響があるか？",
        options=EQUITY_5,
        keywords=["公平", "格差", "地域", "施設間", "アクセス", "高齢", "社会経済", "保険", "入手", "供給"],
        usually_absent_in_gl=True,
    ),
    Criterion(
        id="acceptability",
        order=10,
        label_ja="受容性",
        question_ja="主要な関係者にとって介入は受け入れ可能か？",
        options=YES_NO_5,
        keywords=["受容", "受け入れ", "許容", "負担", "アドヒアランス", "継続", "忍容", "不快", "拒否", "希望しない", "同意"],
        usually_absent_in_gl=True,
    ),
    Criterion(
        id="feasibility",
        order=11,
        label_ja="実行可能性",
        question_ja="介入の実施は現実的か？",
        options=YES_NO_5,
        keywords=["実施可能", "実行可能", "実現", "体制", "施設", "普及", "供給", "入手", "承認", "適応", "製造", "販売", "回収", "人員", "手技", "研修"],
        usually_absent_in_gl=True,
    ),
]

CRITERIA_BY_ID: dict[str, Criterion] = {c.id: c for c in CRITERIA}


def allowed_judgments(criterion_id: str) -> list[str]:
    """その基準で許容される判断文字列（NO_INFO / TO_BE_JUDGED を含む）。"""
    return list(CRITERIA_BY_ID[criterion_id].options) + [NO_INFO, TO_BE_JUDGED]


# 推奨タイプ（EtD の結論部）
RECOMMENDATION_TYPES = [
    "介入に反対する強い推奨",
    "介入に反対する条件付き推奨",
    "介入または比較対照のいずれかに対する条件付き推奨",
    "介入を支持する条件付き推奨",
    "介入を支持する強い推奨",
    "推奨なし",
    NO_INFO,
]
