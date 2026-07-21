# PageIndex - for Shinsa

forked from the [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex).

LLMを使ったPDF文書のインデックス作成・検索ツールです。

## 環境準備

```bash
source .venv/bin/activate   # Python仮想環境
```

> スキャンPDF(テキスト層なし)はOCR(vision model)でフォールバック抽出します。Ollamaでvision modelをGPUオフロードするには `/etc/systemd/system/ollama.service.d/override.conf` に `Environment="LLAMA_ARG_MMPROJ_OFFLOAD=1"` を設定し、`sudo systemctl restart ollama` してください(未設定でも動作しますが、OCRがCPU実行になり大幅に遅くなります)。

## 1. インデックス作成

```bash
python run_pageindex.py /path/to/document.pdf
python run_pageindex.py --list
python run_pageindex.py --delete <doc_id>
```

`data/`にインデックス済みドキュメントが保存されます。
設定は`config.yaml`

`--list`で索引済み文書の`doc_id`を確認できます。`--delete`は索引キャッシュのみを
削除し、元のPDF（`data/docs/`）は残ります。

## 2. 質問する

```bash
python run_query.py "質問文"
python run_query.py "質問文" --log /tmp/llm_io.jsonl
```

複数の文書がインデックス済みの場合は、質問内容に応じて最も関連する文書が自動選択されます。
`--log`を指定するとLLMの入出力をjsonl形式で出力。
