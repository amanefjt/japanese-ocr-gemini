# トラブルシューティングログ (troubleshooting_log.md)

発生したエラー内容、原因、解決策、再発防止策を記録します。

## [2026-02-12] Git構成の修正
- **事象**: ホームディレクトリがGitルートになっていた。
- **原因**: 以前の作業で不適切に `git init` またはリポジトリが構成されていた可能性がある。
- **対策**: プロジェクトディレクトリを明示的に `git init` し、GitHubリモートを追加。適切な `.gitignore` を設定。

## [2026-03-10] Google GenAI SDK の型エラー
- **事象**: `gemini-2.0-flash` または `gemini-3-flash-preview` 使用時に、`contents` 引数の型エラー（`Input should be an instance of Image` 等）が発生。
- **原因**: SDK のバージョンにより、画像データを辞書形式で渡すとバリデーションエラーになる場合がある。
- **解決策**: `genai.types.Part.from_bytes(data=image_data, mime_type="image/jpeg")` を使用して明示的に Part オブジェクトを生成して渡す。
- **再発防止策**: 型ヒントを活用し、SDK の `types` モジュールを介したオブジェクト生成を標準とする。
