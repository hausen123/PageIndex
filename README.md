# PageIndex - for Shinsa.

[VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex)のフォークです。

ローカルモデル（Ollama等）を使ったインデックス作成・検索のツール群。

## 環境準備

```bash
source .venv/bin/activate   # Python仮想環境
ollama list                 # 使用するモデルがpull済みか確認
```

APIキー等の環境変数は不要（Ollama経由でローカルにアクセスするため）。

## 1. インデックス作成

```bash
python3 run_pageindex.py /path/to/document.pdf
python3 run_pageindex.py /path/to/document.md
```

`agent/workspace/`にインデックス済みドキュメントが保存されます（PDF/Markdown
はファイル拡張子で自動判別）。詳細な挙動（要約生成の有無など）は
`pageindex/config.yaml`で設定します。

## 2. 質問する

```bash
python3 run_agent.py "質問文"
python3 run_agent.py "質問文" --model ollama_chat/qwen3:14b
python3 run_agent.py "質問文" --io-log /tmp/my_run_io.jsonl
```

`agent/guarded_agent.py`を使用しており、`get_page_content`を最低1回呼ぶまで
回答を確定させない仕組みになっています（詳細は同ファイルのdocstring参照）。
`--io-log`を指定すると`agent/llm_io_logger.py`経由でLLM呼び出しの入出力を
JSONLに記録します。`agent/io_logs/`に参考ログがあります。
