# PageIndex ツリー構築パイプライン解析レポート

対象: `pageindex/page_index.py` / `pageindex/utils.py`（本セッションでの検証・修正を踏まえた分析）

## 1. 全体像

`page_index_main()` → `tree_parser()` が起点。処理は大きく3段階：

1. **PDFをページ単位のテキスト＋トークン数リストに変換**（`get_page_tokens`）
2. **目次（TOC）を検出し、各セクションに物理ページ番号を割り当てる**（本レポートの中心）
3. **粒度が粗すぎる（ページ数/トークン数が多すぎる）ノードを再帰的に細分化**（`process_large_node_recursively`）
4. **ノードごとにsummary/descriptionをLLM生成**（`page_index_main`内、任意）

今回の検証で発覚した不具合はすべて**2の中の「LLM出力の型がPageIndexの想定と食い違うとクラッシュする」箇所**に集中していた。

## 2. TOC検出〜物理ページ割当ての詳細フロー

### 2-1. TOCページの発見 (`check_toc` → `find_toc_pages`)
文書の先頭から数ページずつLLMに投げ、「目次らしきページ」を`toc_detector_single_page`で判定。見つかった場合、`toc_extractor`でそのページ群のテキストを結合し、`detect_page_index`で「目次内にページ番号が書かれているか」を判定する。

### 2-2. 分岐点：`tree_parser`
```
check_toc_result["page_index_given_in_toc"] == "yes"
  → process_toc_with_page_numbers   （目次に印字ページ番号あり：最速・最高精度パス）
  それ以外
  → process_no_toc                  （目次なし/番号なし：全文書を読んで一から構造生成）
```

### 2-3. メインパス: `process_toc_with_page_numbers`
1. `toc_transformer`: 目次の生テキストを `{structure, title, page}` のJSON配列に整形（1回のLLM呼び出し、不完全なら`continue`で追記）
2. `toc_index_extractor`: 目次直後の`toc_check_page_num`ページ分（デフォルト20〜今回40に変更）の本文を渡し、各目次タイトルが実際にどの物理ページ(`<physical_index_N>`タグ)にあるかをLLMに特定させる
3. `extract_matching_page_pairs` + `calculate_page_offset`: 「印字ページ番号」と「物理ページ番号」のペアから**差分（オフセット）**を多数決で算出
4. `add_page_offset_to_toc_json`: 全目次項目の印字ページ番号にオフセットを一律加算して物理ページ番号に変換
5. `process_none_page_numbers`: オフセット変換で埋まらなかった項目を、前後の項目の物理ページ範囲内でLLMに個別検索させて埋める

→ **この設計の急所は3.**：オフセット計算に使う「マッチしたペア」が`toc_check_page_num`ページ以内で見つからない（＝LLMが目次タイトルを本文中に発見できない）と`offset=None`になり、以降の項目が全部埋まらない。506ページの密な日本語文書でローカルモデル4種すべてがここで実質崩壊していた。

### 2-4. フォールバック1: `process_toc_no_page_numbers`
目次はあるが印字ページ番号がない場合（またはメインパスが精度不足で失敗した場合）。目次テキストのみから`toc_transformer`でJSON化し、`toc_index_extractor`で本文全体との対応付けを試みる。

### 2-5. フォールバック2: `process_no_toc`
目次すら使わず、文書全体をトークン数ベースでチャンク分割（`page_list_to_group_text`, 上限20,000トークン/チャンク）し、`generate_toc_init`（最初のチャンク）→`generate_toc_continue`（以降のチャンクを前チャンクの構造を見せながら継続生成）で一から構造を組み立てる。**最も汎用的だが、チャンク数が多いほどLLM呼び出し回数が線形に増え、途中の1回でも壊れると後続が総崩れになりやすい。**

### 2-6. 検証と自己修復 (`meta_processor`の分岐ロジック)
```python
accuracy, incorrect_results = await verify_toc(...)
if accuracy == 1.0 and 不一致0件:        return 確定
elif accuracy > 0.6 and 不一致あり:      fix_incorrect_toc_with_retries で個別修正して確定
else:                                     一段階上位のフォールバックへ委譲
    (process_toc_with_page_numbers → process_toc_no_page_numbers → process_no_toc → 諦めて例外)
```
`verify_toc`自体は「各項目のタイトルが、割り当てられた物理ページの本文中に実在するか」をLLMにサンプリング確認させる仕組み（`single_toc_item_index_fixer`で該当タイトルを含む正しいページを再探索）。

さらに`verify_toc`には早期リターンがあり、**最後に有効なphysical_indexが文書の半分未満にしか到達していない場合、精度チェックすら行わずaccuracy=0を返す**（`last_physical_index < len(page_list)/2`）。qwen3系がここに引っかかっていた＝物理ページ割当てが文書後半にほぼ届いていなかった。

### 2-7. 仕上げ処理
- `add_preface_if_needed`: 先頭セクションの前に空白があれば"Preface"ノードを補う
- `check_title_appearance_in_start_concurrent`: 各タイトルが本当にそのページの冒頭にあるかを並列LLM確認（`appear_start`フラグ付与、post_processingで階層構築に利用）
- `post_processing`（utils.py）: フラットな`{structure: "1.2.3", ...}`リストを、`structure`の数値階層に基づいてネストしたツリーに変換
- `process_large_node_recursively`: 1ノードのページ数が`max_page_num_each_node`（既定10）超過**かつ**トークン数が`max_token_num_each_node`（既定20,000）以上の場合、そのノード範囲だけを`process_no_toc`で再帰的に再分割

## 3. 今回の検証で発見・修正したバグ（全5件）

いずれも「gemma4/qwen3がGPT-4o/GPT-5.6ほど厳密にJSON形式を守らない」ことで露呈した、**LLM出力の型に対する防御不足**。

| # | 箇所 | 症状 | 原因 |
|---|---|---|---|
| 1 | `process_none_page_numbers` (674行目) | `KeyError: 'page'` | `del item_copy['page']`がキー不在を想定せず |
| 2 | `process_none_page_numbers` (676行目) | `KeyError: 0` | `result[0]`がLLM応答が空リストの場合に存在しない |
| 3 | `process_no_toc` (578行目) | `AttributeError: 'dict' has no attribute 'extend'` | `extract_json`がパース失敗時`{}`を返すのに`.extend()`前提 |
| 4 | `validate_and_truncate_physical_indices` (1133行目) | `TypeError: str > int` | `convert_physical_index_to_int`が`<physical_index_N>`形式に一致しない文字列を無変換のまま通す |
| 5 | `add_page_offset_to_toc_json` (408行目) | `TypeError: int + NoneType` | `calculate_page_offset`が仕様上`None`を返しうるのに呼び出し側が未対応 |

いずれもリポジトリの直近コミット（`f413c66`, #188「prevent KeyError crash」）で類似の防御が多数追加されていたが、**GPT系モデルでは発生しないエッジケース**だったため見落とされていたパターン。すべてtry/exceptではなく「型チェック＋グレースフルなフォールバック（Noneに落として後続の未割当処理に委ねる）」で修正済み。

## 4. 設計上のボトルネック（バグではなく仕様の限界）

1. **`toc_transformer`は「目次全体を1回のLLM呼び出しでJSON化」する設計** — 項目数が多い（今回は約90項目）ほど、出力トークン数が増え、途中で壊れるリスクが線形に増加する
2. **オフセット方式はToC全体に単一の一律オフセットを仮定** — 章立ての途中で丁合いが変わる文書（付録・別紙など印字ページ番号がリセットされる文書）では原理的に破綻しうる
3. **`process_no_toc`のチャンク継続生成は「直前のチャンクの結果」しか参照しない** — チャンク数が多い巨大文書では、途中のチャンクで生成ミスが起きても後続に伝播したまま検出されない
4. 文書全体を分割して個別に`page_index`にかけ、後からマージする仕組みは**現状存在しない** — 506ページ超の巨大文書をローカル非力モデルで扱うには、この分割処理を新規実装する必要がある
