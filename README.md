# PageIndex - for Shinsa

forked from the [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex).

LLMを使ったPDF文書のインデックス作成・検索ツールです。

## 環境準備

```bash
source .venv/bin/activate   # Python仮想環境
```

## 1. インデックス作成

```bash
python run_pageindex.py /path/to/document.pdf
```

`data/`にインデックス済みドキュメントが保存されます。設定は`config.yaml`

## 2. 質問する

```bash
python run_query.py "質問文"
python run_query.py "質問文" --log /tmp/llm_io.jsonl
```

複数の文書がインデックス済みの場合は、質問内容に応じて最も関連する文書が自動選択されます。
`--log`を指定するとLLMの入出力のログを出力します。
