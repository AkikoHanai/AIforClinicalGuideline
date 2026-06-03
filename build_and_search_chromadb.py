"""
build_and_search_chromadb.py — チャンク解析 + ChromaDB構築

チャンク形式：
{
    'id': 'chunk_XXX',
    'content': 'テキスト内容',
    'metadata': {
        'Chapter_or_CQ': 'CQ 1' or 'Introduction' etc.,
        'Section': 'Background' / 'PICO' / 'Evidence' / 'RoB' etc.,
        'page': 21,
        'source': 'filename.pdf',
        'etd_metadata': {...}  # optional
    }
}
"""

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions


def parse_chunks_file(file_path: str) -> List[Dict[str, Any]]:
    """
    チャンクテキストファイルをパース。
    形式: JSON行またはPython辞書リストの形式に対応
    """
    chunks = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 試し1: JSON行形式
    for line in content.strip().split('\n'):
        if not line.strip():
            continue
        try:
            chunk = json.loads(line)
            if isinstance(chunk, dict) and 'content' in chunk and 'metadata' in chunk:
                chunks.append(chunk)
        except json.JSONDecodeError:
            pass

    if chunks:
        return chunks

    # 試し2: Python辞書リスト形式
    try:
        data = ast.literal_eval(content)
        if isinstance(data, list) and all(isinstance(c, dict) for c in data):
            return data
    except Exception:
        pass

    # 試し3: 単純なMarkdown形式（各見出しがチャンク）
    # # CQ1\nテキスト\n## Section\n...
    sections = re.split(r'^#+\s+', content, flags=re.MULTILINE)
    if len(sections) > 1:
        for i, section in enumerate(sections[1:], 1):
            lines = section.strip().split('\n', 1)
            title = lines[0] if lines else f'section_{i}'
            text = lines[1] if len(lines) > 1 else ''

            chunk = {
                'id': f'chunk_{i:03d}',
                'content': text.strip(),
                'metadata': {
                    'Chapter_or_CQ': title,
                    'Section': 'content',
                    'source': Path(file_path).name,
                }
            }
            chunks.append(chunk)
        return chunks

    raise ValueError(f"チャンクファイルの形式を認識できません: {file_path}")


def normalize_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """ChromaDB用にメタデータを正規化（スカラー型のみ）"""
    out = {}
    for k, v in (meta or {}).items():
        if v is None:
            out[k] = ""
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = json.dumps(v, ensure_ascii=False)
    return out


def build_chromadb(chunks_data: List[Dict[str, Any]], collection_name: str = "guidelines_collection"):
    """
    チャンクデータをChromeDBに投入
    """
    client = chromadb.Client()

    # 既存のコレクションを削除（安全のため）
    try:
        client.delete_collection(name=collection_name)
    except Exception:
        pass

    # 埋め込みモデルの設定（フォールバック）
    try:
        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )
    except Exception:
        print("⚠️  SentenceTransformer は利用不可。デフォルト埋め込みを使用...")
        embedding_fn = embedding_functions.DefaultEmbeddingFunction()

    collection = client.create_collection(
        name=collection_name,
        embedding_function=embedding_fn
    )

    # チャンクを投入
    documents = []
    metadatas = []
    ids = []

    for chunk in chunks_data:
        documents.append(chunk['content'])
        metadatas.append(normalize_metadata(chunk.get('metadata', {})))
        ids.append(chunk.get('id', f'chunk_{len(ids):03d}'))

    # バッチで投入
    batch_size = 10
    for i in range(0, len(documents), batch_size):
        end = min(i + batch_size, len(documents))
        collection.add(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=ids[i:end]
        )
        print(f"  Batch {i}-{end}: loaded")

    print(f"✅ ChromaDB構築完了: {len(documents)}件のチャンクを投入")
    return client, collection


def search_chromadb(collection, query: str, cq_filter: Optional[str] = None, top_k: int = 5):
    """
    ハイブリッド検索
    query: 検索クエリ
    cq_filter: CQ名（オプション）
    top_k: 取得件数
    """
    results = collection.query(
        query_texts=[query],
        n_results=top_k
    )

    # CQフィルタを適用
    if cq_filter:
        cq_norm = cq_filter.replace(" ", "").upper()
        filtered_results = []
        for doc, meta, score in zip(
            results.get('documents', [[]])[0],
            results.get('metadatas', [[]])[0],
            results.get('distances', [[]])[0]
        ):
            chapter = str(meta.get('Chapter_or_CQ', '')).replace(" ", "").upper()
            if cq_norm in chapter or chapter == cq_norm:
                filtered_results.append({
                    'content': doc,
                    'metadata': meta,
                    'distance': score
                })
        return filtered_results[:top_k]

    return [{
        'content': doc,
        'metadata': meta,
        'distance': score
    } for doc, meta, score in zip(
        results.get('documents', [[]])[0],
        results.get('metadatas', [[]])[0],
        results.get('distances', [[]])[0]
    )]


if __name__ == "__main__":
    # テスト用
    import sys
    if len(sys.argv) > 1:
        chunks_file = sys.argv[1]
        chunks = parse_chunks_file(chunks_file)
        print(f"パース完了: {len(chunks)}件")
        client, col = build_chromadb(chunks)

        # サンプル検索
        if len(sys.argv) > 2:
            query = sys.argv[2]
            results = search_chromadb(col, query)
            for i, r in enumerate(results, 1):
                print(f"\n[{i}] {r['metadata'].get('Chapter_or_CQ', 'N/A')}")
                print(f"    {r['content'][:100]}...")
