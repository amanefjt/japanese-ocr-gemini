# 調査+実機検証記録: Mac標準機能(オンデバイスLLM)による縦書き史料OCRショートカット

**初出**: 2026-07-15（p2workflowyリポジトリでのブレインストーミング）
**実機検証**: 2026-07-22（本リポジトリ、gocr）
**ステータス**: **実機検証の結果、現状の環境(macOS 26.5.2)では実用不可と判明。macOS 27 / Xcode 27待ちで保留**
**位置づけ**: このアイデアは元々 `p2workflowy` リポジトリの `docs/superpowers/specs/2026-07-15-vertical-text-ocr-shortcut-design.md` にその場の壁打ちとして記録されていたが、内容的な本籍はgocr(日本語縦書きOCRプロジェクト)にあるため、実機検証を機にこちらへ移した。p2workflowy側のファイルは経緯の記録として残置している。

---

## 1. 問題設定（2026-07-15 時点の背景）

NDL OCR（および軽量フォーク版）は日本語縦書きの文字認識精度自体は高いが、**画像上の行末で機械的に改行を入れる**ため、原文では連続しているはずの段落が行ごとにブツ切りのテキストになる。これは「文字認識（Vision/OCRエンジンの役割）」と「意味的な段落復元（言語理解の役割）」が別工程である以上、原理的に避けられない構造的limitationである。

gocr自体はこの問題を「OCR単体を挟まず、画像を直接クラウドのGemini APIに渡す」ことで回避している（`processor/gemini_extractor.py`）。今回検討したのは、その**オンデバイス版**（Apple Foundation Models、無料・ローカルファースト）が同じ思想で成立するか、という調査。

## 2. 検討した選択肢とその整理（2026-07-15 時点）

| # | 選択肢 | 却下/採用理由 |
|---|---|---|
| 1 | ルールベース後処理（文末記号・行頭インデント判定の正規表現） | 誤字・ルビ混入・短い見出し行などで簡単に破綻する |
| 2 | NDL OCR → 外部LLM API（Claude/GPT-4o）でテキストのみ後処理 | 画像側の空間情報（インデント・段組配置）が失われ、ハルシネーションの温床になる |
| 3 | 画像を直接マルチモーダルLLM（Claude/GPT-4o Vision）に投入し一括処理 | 精度面では最有力だが、外部クラウドAPIへの送信が前提でローカルファースト方針に反する |
| 4 | Mac標準OCR（Live Text）+ Apple Intelligence Writing Toolsで後から整形 | 実質的に選択肢2と同じ二段階構造で、空間情報の欠落問題は解消しない |
| 5 | サードパーティのローカルLLM（Ollama等）を導入して自前構築 | 追加インストールが必要で配布性の要件を満たさない |
| 6 | **Apple Foundation Models framework / Shortcutsの「モデルを使用」で、画像を直接オンデバイスLLMに渡し一括処理** | **採用（設計上は）**。追加インストール不要、完全オンデバイス、ローカルファースト、配布性も高い |

## 3. WWDC2026マルチモーダル対応の確認（2026-07-15）

選択肢6の検討時、当初「Apple純正フレームワークはテキスト入力オンリー」という誤った前提で「実現不可能」と判定したが、WWDC2026（2026年6月8日）で以下が発表されていたことをWeb検索で確認：

- Foundation Models frameworkが`LanguageModelSession`に`.image()`コンテンツブロックを追加しマルチモーダル対応（[WWDC26 session 241](https://developer.apple.com/videos/play/wwdc2026/241/)）
- ノーコードのShortcutsアプリ「モデルを使用」アクションも、iOS/macOS 26の時点で写真を入力に含められるとApple公式ヘルプに記載（[Apple公式サポート](https://support.apple.com/guide/mac-help/use-apple-intelligence-in-shortcuts-mchl91750563/mac)）
- `fm` CLIとPython SDK（`apple-fm-sdk`）も新設（[WWDC26 session 334](https://developer.apple.com/videos/play/wwdc2026/334/)）

これを踏まえ、「画像を直接オンデバイスLLMに渡し、段落復元済みテキストを一発で得る」設計（見開き判定→中点クロップ→各画像をループで「モデルを使用」→結合→ファイル出力）を確定した。詳細な設計判断ログは省略（元の意思決定は概ね妥当だったため、本ドキュメントでは4節以降の実機検証を主眼とする）。

## 4. 関連: gocr内での類似アーキテクチャの先行検討（コスト理由でキャンセル）

gocrには実は similar な「軽量OCR→LLMでテキストのみ段落整形」というハイブリッド構成の検討履歴が既にあった: `docs/superpowers/specs/2026-05-10-ndl-hybrid-ocr-design.md`（NDL OCR Lite + Geminiテキスト整形、トークン50%削減が目的）。ただしこちらは**2026-05-10にキャンセル済み**（`gemini-3.1-flash-lite-preview`が安価すぎて50%削減の絶対額が無意味だったため。1000ページ≈¥10）。

今回のオンデバイスLLM案は動機が異なる（コスト削減ではなくローカルファースト・無料・プライバシー）が、「画像認識と段落復元を分業する」という構造自体は同じパターン。NDLハイブリッド案がコスト面で不採用になったのに対し、オンデバイス案は以下の通り**別の壁（ガードレール）**で行き詰まった。

---

## 5. 2026-07-22 gocrでの実機検証

### 5.1 検証環境

- macOS 26.5.2（Build 25F84）
- Apple M5 / arm64
- Xcode 26.6（Build 17F113）、Swift 6.3.3
- サンプルPDF: `Sample/ethnopdfselected.pdf`（縦書き見開き一段組、7ページ）、`Sample/matsumura.pdf`（縦書き見開き二段組、5ページ）
- 実験venv: `~/.venvs/gocr`（pCloud Drive配下の`gocr/.venv`はシンボリックリンク作成不可のため、pCloud同期外に作成）
- 実験スクリプト: `tests/experiment_ondevice_ocr.py`（`apple-fm-sdk`経由の画像直接投入ルートを試すために作成。gocrの`processor/image_detector.py`・`processor/prompts.py`を直接importして流用）

### 5.2 ルート1: Python SDK（`apple-fm-sdk`）— 画像添付が不可

`pip install apple-fm-sdk`でインストール後、`SystemLanguageModel().is_available()`は`True`（オンデバイスモデル自体は利用可能）。テキストのみの呼び出しは成功：

```python
session = fm.LanguageModelSession()
r = await session.respond("こんにちは、と一言だけ日本語で返してください。")
# => "こんにちは！"
```

しかし`fm.ImageAttachment`で画像を渡すと、インストール時にローカルのXcodeでビルドされるSwiftバインディングが原因で以下のエラー：

```
ImagePromptError: Failed to add attachment to prompt: the Xcode version used to build
this package doesn't include macOS 27 SDKs
```

`apple-fm-sdk`公式ドキュメントは「macOS 26.0+で動作」と記載しているが、**画像添付（マルチモーダル）機能はXcode/macOS 27 SDKでのビルドを要求する**ことが判明。手元のXcode 26.6では不可。`fm` CLI自体も「macOS 27にプリインストール」という情報と整合する（[出典](https://byteiota.com/apple-foundation-models-wwdc-2026-multimodal-python-sdk/)）。

### 5.3 ルート2: Shortcuts GUI「モデルを使用」— 画像が実質無視される

OS純正のShortcutsアプリはXcodeのローカルビルドに依存しないため、画像添付が機能する可能性を試した。

- 「ファイルを選択」→「PDFからイメージを作成」→「1ページ目を取得」→「モデルを使用」（オンデバイス、画像を変数として挿入）という構成を手動で作成
- 実行結果:
  - 1回目のプロンプト（「この画像に写っている文章をそのまま書き起こして」）:
    > 申し訳ありませんが、その画像をそのまま提供することはできません。
  - プロンプトを言い回し変更（「そのまま提供」を避け「画像自体は不要、文字だけをテキストとして出力」と明示）しても:
    > 申し訳ございませんが、その画像を直接分析することはできません。ただし、テキストを入力していただければ、お手伝いできることがございます。

2回目の応答文言（「テキストを入力していただければ」という誘導）から、**プロンプトの言い回しの問題ではなく、画像がそもそもモデルに画像として届いていない**（テキストオンリーモデルとしてフォールバックしている）と判断。ルート1の「macOS 27 SDK要求」と整合しており、Shortcuts GUIの「モデルを使用」も、この時点のmacOSバージョンでは画像入力が実質機能していないと結論づけた。

### 5.4 方針転換: 役割分割型（Vision OCR + LLM段落復元）

画像を直接LLMに渡す案が2ルートとも塞がっていたため、design memo自体が当初「選択肢2」として却下していた二段階構成（Vision framework「テキストを認識」で文字認識 → 「モデルを使用」でテキストのみ渡して段落復元）に一時的に切り替えて検証を継続。

このステップで、パイプラインの実装ミスを発見・修正：
- 「ファイルからJPEG画像を作成」に複数ページPDFを渡すと画像のリストが返るが、後続に「1ページ目だけ取り出す」ステップが抜けていたため、7ページ全部のOCR結果（6068文字）が1つに結合されてしまい「リクエストの長さが指定可能な上限を超えています」エラーが発生
- 「リストから項目を取得」（インデックス1）を画像リストの直後に追加して修正。1ページ分のOCRテキストは867文字程度（6068 ÷ 7ページ）と、通常の本文ページとして妥当な文字数であることを確認

### 5.5 本命の壁: 出力量に対するガードレール（コンテキスト窓ではない）

修正後、1ページ分（867文字）のテキストを段落復元プロンプトに渡すと、今度は別のエラー：

```
モデルでこのリクエストに対する応答を提供できません。リクエストを修正して、やり直してみてください。
```

原因切り分けのため文字数を変えて実験：

| 文字数 | 結果 |
|---|---|
| 30文字程度（ベタ打ちの短文） | OK |
| 118文字 | OK |
| 228文字 | NG |
| 360文字 | NG |
| 867文字（1ページ分） | NG |
| 6068文字（7ページ分、バグ由来） | NG（長さ超過） |

**壁は118〜228文字という、驚くほど低いところにあった。** ベタ打ちの短文（原文をほぼそのまま出力させる指示）は通ったことから、「原文通りに出力させる」という指示内容自体が恒常的に禁止されているわけではない。したがってこれは:

- コンテキスト窓（トークン上限）の問題ではない（それなら数千文字は許容されるはず）
- **「入力とほぼ同じ内容を大量に出力させる（＝ほぼ複製に近い）タスク」に対する、出力量そのもののガードレール制限**である可能性が非常に高い

この推測は、Python SDKのドキュメントで見つけた`SystemLanguageModelGuardrails`列挙型の存在と整合する:

```python
model = fm.SystemLanguageModel(
    guardrails=fm.SystemLanguageModelGuardrails.PERMISSIVE_CONTENT_TRANSFORMATIONS
)
```

`PERMISSIVE_CONTENT_TRANSFORMATIONS`は「入力内容をほぼそのまま出力する変換タスク（＝まさにOCR）」向けの緩和オプションと解釈できる。裏を返すと、**デフォルトのガードレールはこの種のタスクの出力量を数百文字未満に制限しており、この緩和オプションはコード（Swift/Python SDK）からしか設定できず、ShortcutsのGUIからは選択肢すら存在しない**。

## 6. 結論（2026-07-22時点）

1ページ（800〜900文字）を処理するには120〜200文字ずつ5〜7回に分割してモデルを呼ぶ必要があり、
- 呼び出し回数が激増し非現実的
- 断片の境目で文脈がさらに壊れやすくなる（皮肉にも、この設計が解決しようとしていた「行末での機械的な断片化」と同種の問題を、モデル呼び出しの単位で再発させる）
- 断片ごとにガードレールの反応が一貫しない可能性もある

という理由で、**画像直接投入・テキスト後処理のいずれの構成でも、Shortcuts GUI（デフォルトガードレール）経由では今回のOCR/段落復元タスクは実用的に成立しない**と判断した。これはプロンプトやパイプライン構成の問題ではなく、macOS 26.5.2時点のプラットフォーム制約（画像入力の未対応 + デフォルトガードレールの出力量制限）に起因する。

唯一残る突破口は、Python SDK経由で`guardrails=PERMISSIVE_CONTENT_TRANSFORMATIONS`を明示的に指定するルートだが、それには5.2で判明した「Xcodeがmacos27 SDKを要求する」壁が別途立ちはだかっている。

## 7. 次にやること（保留中の再開条件）

1. macOS 27 / 対応するXcodeがGA（一般提供）された時点で、`apple-fm-sdk`の`ImageAttachment`と`guardrails=PERMISSIVE_CONTENT_TRANSFORMATIONS`の組み合わせを再検証する
2. 再検証時は本ドキュメント5.4-5.5の文字数実験を踏襲し、ガードレール緩和後に実用的な文字数（最低でも1ページ分、理想的には見開き全体）まで通るか確認する
3. Xcode beta（Apple Developer Program登録があれば）で前倒し検証する選択肢もあり得るが、2026-07-22時点では未着手
4. gocr本体（Gemini APIパイプライン）は現状維持。このオンデバイス案はコスト・プライバシー面での将来オプションとして保留する

## 8. 参考資料

- [What's new in the Foundation Models framework (WWDC26 session 241)](https://developer.apple.com/videos/play/wwdc2026/241/)
- [Build AI-powered scripts with the fm CLI and Python SDK (WWDC26 session 334)](https://developer.apple.com/videos/play/wwdc2026/334/)
- [Foundation Models SDK for Python ドキュメント](https://apple.github.io/python-apple-fm-sdk/)
- [Use Apple Intelligence in Shortcuts on Mac（Apple公式サポート）](https://support.apple.com/guide/mac-help/use-apple-intelligence-in-shortcuts-mchl91750563/mac)
- [Apple Foundation Models WWDC 2026: Multimodal + Python SDK (byteiota)](https://byteiota.com/apple-foundation-models-wwdc-2026-multimodal-python-sdk/)
- p2workflowyの元記録: `p2workflowy/docs/superpowers/specs/2026-07-15-vertical-text-ocr-shortcut-design.md`（2026-07-15のブレインストーミング全文はこちらに残置）
- gocr内の関連先行検討（コスト理由でキャンセル）: `docs/superpowers/specs/2026-05-10-ndl-hybrid-ocr-design.md`
