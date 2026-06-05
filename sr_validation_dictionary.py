"""
sr_validation_dictionary.py — 検証用辞書（医学用語の同義語）

PICO マッチングの精度向上用に、医学的な同義語や言い換え表現を定義
"""

# PICO 医学用語辞書
MEDICAL_SYNONYMS = {
    # Population (P) - 対象者
    "population": ["患者", "対象", "参加者", "患者群"],
    "cancer_survivor": ["がんサバイバー", "がん経験者", "がん患者", "がん完治患者"],
    "adolescent": ["思春期", "青少年", "若年者"],
    "adult": ["成人", "大人", "患者"]  ,
    "elderly": ["高齢者", "高齢", "老年"],

    # Intervention (I) - 介入
    "exercise": ["運動", "身体活動", "運動介入", "トレーニング", "リハビリ"],
    "physical_activity": ["身体活動", "運動", "活動量"],
    "aerobic": ["有酸素", "有酸素運動"],
    "resistance": ["筋力", "筋力運動", "レジスタンス", "抵抗運動"],
    "combined": ["複合", "統合", "併用"],

    # Comparison (C) - 対照
    "usual_care": ["通常のケア", "標準的ケア", "標準治療", "対照"],
    "placebo": ["プラセボ", "偽薬", "対照"],
    "no_intervention": ["介入なし", "運動なし", "対照群"],
    "low_intensity": ["低強度", "低強度運動"],

    # Outcome (O) - アウトカム
    "quality_of_life": ["QoL", "生活の質", "QOL", "生活質"],
    "physical_fitness": ["体力", "フィットネス", "身体機能"],
    "strength": ["筋力", "強度"],
    "fatigue": ["倦怠感", "疲労", "疲弱感"],
    "depression": ["うつ", "抑うつ", "抑うつ症状"],
    "anxiety": ["不安", "焦燥感"],
    "safety": ["安全性", "有害事象", "副作用"],
    "cardiovascular": ["心血管", "心肺", "心臓"],
    "mental_health": ["精神健康", "メンタルヘルス", "心理社会的"],
}

# 検証用キーワード辞書
VALIDATION_KEYWORDS = {
    # 推奨方向
    "for": ["推奨", "実施", "for", "should", "推励", "推奨する"],
    "against": ["推奨しない", "実施しない", "against", "should not", "非推奨"],

    # 推奨の強さ
    "strong": ["強い", "強く", "strong", "should", "必須", "推奨"],
    "weak": ["弱い", "弱く", "weak", "may", "could", "提案", "検討"],

    # GRADE 確実性
    "high": ["高", "High", "高い"],
    "moderate": ["中程度", "Moderate", "中等度", "中"],
    "low": ["低", "Low", "低い"],
    "very_low": ["非常に低い", "Very low", "極めて低い"],
}

# バイアスリスク用語
BIAS_RISK_KEYWORDS = {
    "low": ["低", "low", "low risk"],
    "some_concerns": ["いくつかの懸念", "some concerns", "concern"],
    "high": ["高", "high", "high risk"],
}

def get_synonyms(category: str, keyword: str) -> set:
    """
    キーワードから同義語を検索

    Args:
        category: PICO のカテゴリ
        keyword: 検索キーワード

    Returns:
        同義語のセット
    """
    if category in MEDICAL_SYNONYMS:
        keyword_lower = keyword.lower()
        for key, synonyms in MEDICAL_SYNONYMS.items():
            if keyword_lower in key or any(s in keyword_lower for s in synonyms):
                return set(synonyms + [key.replace("_", " ")])
    return {keyword}


def normalize_text(text: str) -> str:
    """医学用語を正規化"""
    text_lower = text.lower()
    # 一般的な変換
    replacements = {
        "がんサバイバー": "cancer survivor",
        "がん経験者": "cancer survivor",
        "運動": "exercise",
        "身体活動": "physical activity",
        "生活の質": "quality of life",
        "qol": "quality of life",
        "有酸素": "aerobic",
        "筋力": "strength",
        "倦怠感": "fatigue",
        "うつ": "depression",
    }

    for jp, en in replacements.items():
        text_lower = text_lower.replace(jp, en)

    return text_lower


if __name__ == "__main__":
    # テスト
    print("医学用語辞書テスト\n")

    test_keywords = [
        "がんサバイバー",
        "運動介入",
        "生活の質",
        "標準的ケア"
    ]

    for keyword in test_keywords:
        normalized = normalize_text(keyword)
        print(f"{keyword} → {normalized}")
