"""
sr_pdf_chunk_extractor.py — PDFからチャンク抽出（CQコンタミ防止）

cancer_survivor_guidelines.pdf → CQごとに厳格に分割
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber


def extract_cq_number(text: str) -> Optional[str]:
    """テキストから CQ番号を抽出（CQ 1, CQ1, CQ1等に対応）"""
    match = re.search(r"(?i)CQ\s*(\d+)", text)
    if match:
        return f"CQ {match.group(1)}"
    return None


def extract_section_name(text: str) -> str:
    """テキストからセクション名を抽出"""
    # 見出しパターン
    patterns = [
        (r"^## (.+?)$", re.MULTILINE),  # Markdown H2
        (r"^【(.+?)】$", re.MULTILINE),  # 【セクション】
        (r"^(\d+\)?\s+.+)$", re.MULTILINE),  # 番号付き見出し
    ]

    for pattern, flags in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1)[:50]

    return "general"


def extract_chunks_from_pdf(
    pdf_path: str,
    output_file: str = "pdf_chunks.json"
) -> List[Dict[str, Any]]:
    """
    PDFからチャンク抽出（CQごとに厳格分割）

    コンタミ防止ロジック:
    - CQ番号で明示的に分割
    - 別CQのテキストは含めない
    - セクション情報で文脈を保持
    """
    chunks = []
    chunk_id = 0

    with pdfplumber.open(pdf_path) as pdf:
        current_cq = None
        current_section = "general"
        current_text_buffer = []
        current_page = None

        # 目次など共通章のページ範囲を特定（最初の数ページ）
        COMMON_PAGE_RANGE = (1, 20)  # 目次はだいたいPage 1-20

        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if not text:
                continue

            # 目次ページはスキップ（CQの本体内容ではない）
            is_toc_page = (
                page_num <= COMMON_PAGE_RANGE[1] and
                any(toc_marker in text for toc_marker in ["目次", "Contents", "■", "引用文献"])
            )
            if is_toc_page:
                continue

            # CQ検出
            cq_match = extract_cq_number(text)
            if cq_match and cq_match != current_cq:
                # CQ切り替え時：バッファをフラッシュ
                if current_text_buffer and current_cq:
                    chunk_id += 1
                    chunks.append({
                        "id": f"chunk_{chunk_id:04d}",
                        "content": "\n".join(current_text_buffer),
                        "metadata": {
                            "Chapter_or_CQ": current_cq,
                            "Section": current_section,
                            "page": current_page,
                            "source": Path(pdf_path).name,
                        }
                    })
                current_text_buffer = []
                current_cq = cq_match
                current_page = page_num

            # セクション検出
            section = extract_section_name(text)
            if section != "general":
                current_section = section

            # スキップセクション検出（複数CQを含む共通セクション）
            skip_sections = ["ガイドラインサマリー", "要約", "Overview", "Summary", "診療アルゴリズム", "診療の流れ"]
            if any(skip in text for skip in skip_sections):
                # 共通章セクションはスキップ
                if current_text_buffer and current_cq:
                    chunk_id += 1
                    chunks.append({
                        "id": f"chunk_{chunk_id:04d}",
                        "content": "\n".join(current_text_buffer),
                        "metadata": {
                            "Chapter_or_CQ": current_cq,
                            "Section": current_section,
                            "page": current_page or page_num,
                            "source": Path(pdf_path).name,
                        }
                    })
                current_text_buffer = []
                current_cq = None  # 共通章後はCQリセット
                continue

            # 単純な heuristic：行ごとにコンテンツを判定
            lines = text.split('\n')
            for line in lines:
                stripped = line.strip()

                # フィルタ：無関係な行をスキップ
                if len(stripped) < 5:
                    continue
                if any(skip in stripped for skip in ["ページ", "Page", "図", "表", "【", "】", "目次", "Contents"]):
                    continue

                # 別CQの開始を検出したら、バッファをフラッシュして新CQを開始
                new_cq = extract_cq_number(line)
                if new_cq and new_cq != current_cq:
                    # ただし、同一行に複数CQがある場合（目次等）はスキップ
                    cq_count = len(re.findall(r"(?i)CQ\s*(\d+)", line))
                    if cq_count > 1:
                        continue

                    if current_text_buffer and current_cq:
                        chunk_id += 1
                        chunks.append({
                            "id": f"chunk_{chunk_id:04d}",
                            "content": "\n".join(current_text_buffer),
                            "metadata": {
                                "Chapter_or_CQ": current_cq,
                                "Section": current_section,
                                "page": current_page or page_num,
                                "source": Path(pdf_path).name,
                            }
                        })
                    current_text_buffer = []
                    current_cq = new_cq
                    current_page = page_num
                    current_section = "general"
                    continue

                current_text_buffer.append(stripped)

        # 最終バッファをフラッシュ
        if current_text_buffer and current_cq:
            chunk_id += 1
            chunks.append({
                "id": f"chunk_{chunk_id:04d}",
                "content": "\n".join(current_text_buffer),
                "metadata": {
                    "Chapter_or_CQ": current_cq,
                    "Section": current_section,
                    "page": current_page or len(pdf.pages),
                    "source": Path(pdf_path).name,
                }
            })

    # ファイルに保存（JSONL形式）
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"✅ チャンク抽出完了: {len(chunks)}件")

    # CQごとのサマリー
    cq_counts = {}
    for chunk in chunks:
        cq = chunk['metadata']['Chapter_or_CQ']
        cq_counts[cq] = cq_counts.get(cq, 0) + 1

    print("\n【CQごとのチャンク数】")
    for cq in sorted(cq_counts.keys()):
        print(f"  {cq}: {cq_counts[cq]}件")

    return chunks


def validate_no_contamination(chunks: List[Dict[str, Any]]) -> bool:
    """
    コンタミチェック：各チャンク内に複数のCQが存在していないか確認
    """
    print("\n【コンタミチェック】")
    contaminated = []

    for chunk in chunks:
        content = chunk['content']
        cq_matches = re.findall(r"(?i)CQ\s*(\d+)", content)
        cqs_in_chunk = set(cq_matches)

        if len(cqs_in_chunk) > 1:
            contaminated.append({
                'chunk_id': chunk['id'],
                'declared_cq': chunk['metadata']['Chapter_or_CQ'],
                'found_cqs': list(cqs_in_chunk),
            })

    if contaminated:
        print(f"⚠️  コンタミ検出: {len(contaminated)}件")
        for item in contaminated[:5]:
            print(f"  {item}")
        return False
    else:
        print("✅ コンタミなし（CQ分離成功）")
        return True


def print_sample_chunks(chunks: List[Dict[str, Any]], cq_target: str, count: int = 2):
    """
    サンプルチャンクを表示
    """
    print(f"\n【{cq_target}のサンプルチャンク】")
    cq_chunks = [c for c in chunks if c['metadata']['Chapter_or_CQ'] == cq_target]

    for chunk in cq_chunks[:count]:
        print(f"\n  ID: {chunk['id']}")
        print(f"  Section: {chunk['metadata']['Section']}")
        print(f"  Page: {chunk['metadata']['page']}")
        print(f"  Content (最初100文字):")
        print(f"    {chunk['content'][:100]}...")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PDFからチャンク抽出（CQコンタミ防止）")
    parser.add_argument("--pdf", required=True, help="入力PDF")
    parser.add_argument("--output", default="pdf_chunks.json", help="出力JSONL")
    args = parser.parse_args()

    chunks = extract_chunks_from_pdf(args.pdf, args.output)
    validate_no_contamination(chunks)

    # サンプル表示
    print_sample_chunks(chunks, "CQ 1", count=1)
    print_sample_chunks(chunks, "CQ 2", count=1)
