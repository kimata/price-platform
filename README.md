# price-platform

商品価格の収集・表示を行う Web アプリケーション群で共通して必要となる基盤機能を提供する Python ライブラリ。

## 背景

カメラレンズ・電動工具・ヘッドホンなど、ジャンル別に運用している複数の価格比較サイトで、認証・設定管理・Web アプリ基盤といった共通コードが重複していた。
これらを一つのライブラリに統合し、コードの品質とアーキテクチャのクリーンさを重視して設計し直すことで、各アプリケーションの保守性を向上させる。

## 提供する機能

### 認証・認可 (`auth`)
- **API トークン**: 短寿命 JWT によるステートレスな API 認証
- **メトリクス認証**: ダッシュボード向けのパスワード認証 + JWT セッション管理
- **パスワードハッシュ**: Argon2id ベースの安全なパスワードハッシュ
- **レートリミッター**: IP ベースのインメモリレートリミッター
- **シークレット管理**: ファイルベースのスレッドセーフなシークレットプロバイダ

### 設定管理 (`config`)
- YAML ファイルから dataclass ベースの型付きモデルへの変換
- 未知キーの検出と typo 候補の提示
- 各ストア API (Amazon, Yahoo, 楽天) やスクレイピング、通知等の設定モデル

### Web アプリ基盤 (`webapp`)
- Flask アプリケーションファクトリ (ProxyFix, CORS, セキュリティヘッダの一括適用)
- パスベースのキャッシュ制御
- リクエストスコープの DB コネクション管理とスロークエリログ

### コンテンツ (`content`)
- About ページの構造化コンテンツモデルと YAML ローダ

## セットアップ

```bash
uv sync
```

`price-platform` は `my-lib` を runtime dependency として利用します。ローカル開発では `../my-py-lib` を参照しても構いません。

### `my-py-lib` との境界

`price-platform` から直接参照してよい `my-py-lib` の低レベル API は以下に限定します。

- `my_lib.sqlite_util`
  - `connect`
  - `init_schema_from_file`
  - `exec_schema_from_file`
  - `recover`
- `my_lib.time`
  - `get_tz`
  - `get_zoneinfo`
  - `now`
- `my_lib.browser_manager`
  - `BrowserManager`
- `my_lib.selenium_util`
  - `create_driver`
  - `quit_driver_gracefully`
  - `clear_cache`
- `my_lib.config`
  - `load`
- `my_lib.webapp.config`
  - `show_handler_list`
- `my_lib.webapp.event`
  - `blueprint`
  - `notify_event`

これら以外の `my_lib` 依存は `price_platform.platform.*` の facade を追加してから使います。`price-platform` 側で同等の低レベル実装を再実装しないことも方針です。

### SQLite schema ownership

`price-platform` 管轄の SQLite schema は `src/price_platform/schema/` が canonical です。対象は次の DB です。

- `sqlite_notification.schema`
- `sqlite_metrics.schema`
- `sqlite_client_metrics.schema`
- `sqlite_price_events.schema`
- `sqlite_webpush.schema`

consumer app 側の `schema/` は override か legacy migration 用にだけ残せますが、baseline schema と migration の owner は `price-platform` です。`schema_dir` override は段階的に廃止する前提です。

共通化のため、DB 列名も canonical 名に寄せています。

- `price_events.selection_key`
- `webpush_subscriptions.group_filter`

アプリ固有の `color_id` / `variant_id` / `maker_filter` / `category_filter` などは migration で吸収します。

### 依存関係

- Python >= 3.11
- Flask >= 3.0
- PyJWT >= 2.8
- argon2-cffi >= 23.1
- flask-cors >= 6.0

## ライセンス

Apache License 2.0
