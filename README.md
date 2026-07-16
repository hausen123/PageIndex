# PageIndex - for Shinsa.

forked from the [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex).

LLMを使ったPDF文書のインデックス作成・検索ツールです。

## 環境準備

```bash
source .venv/bin/activate   # Python仮想環境
```

## 1. インデックス作成

```bash
python3 run_pageindex.py /path/to/document.pdf
```

`data/index/`にインデックス済みドキュメントが保存されます。詳細な挙動（要約生成の有無など）は`config.yaml`で設定します。

## 2. 質問する

```bash
python3 run_query.py "質問文"
python3 run_query.py "質問文" --model ollama_chat/qwen3:14b
python3 run_query.py "質問文" --io-log /tmp/my_run_io.jsonl
```

`data/index/`に複数の文書が索引済みの場合は、質問内容に応じて最も関連する文書が自動選択されます。
`--io-log`を指定すると`src/query_agent/llm_io_logger.py`経由でLLM呼び出しの入出力をJSONLに記録します。`logs/`に参考ログがあります。
