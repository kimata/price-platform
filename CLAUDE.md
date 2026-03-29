# CLAUDE.md

## プロジェクト概要

price-platform は、商品価格の収集・表示を行う複数の Web アプリケーション間で共通する基盤コードをライブラリとして提供するプロジェクト。
各アプリケーション（カメラレンズ、電動工具、ヘッドホン等）が個別に持っていた認証・設定管理・Web アプリ基盤などの重複コードを括り出し、一つの Python パッケージとして整理している。

## 設計方針

- **クリーンなアーキテクチャを最優先する**: 既存アプリケーションとの互換性を保つために中途半端な抽象化を行わない。必要であれば利用側アプリケーションを大きくリファクタリングする前提で、このライブラリの API 設計を優先する。
- **既存コードを壊すことを恐れない**: ライブラリ化にあたって既存の各アプリケーションの構造を積極的にリファクタリングする。安全側に倒して汚い互換レイヤーを残すよりも、思い切った変更を選ぶ。
- **関心の分離を徹底する**: 各モジュール (auth, config, webapp, content) は明確な責務を持ち、相互依存を最小限に保つ。
- **設定より規約**: dataclass ベースの型付き設定モデルを使い、設定の構造をコードで表現する。

## 技術スタック

- Python 3.12+, Flask, PyJWT, argon2-cffi
- ビルド: hatchling (pyproject.toml)
- リンター: ruff (.ruff.toml)
- フォーマッター: prettier (.prettierrc, フロントエンド向け)

## パッケージ構成

```
src/price_platform/
├── auth/           # 認証・認可 (API トークン, JWT, パスワードハッシュ, レートリミッター)
├── config/         # 設定ロード・バリデーション (YAML → dataclass)
├── content/        # コンテンツモデル (About ページ等)
└── webapp/         # Flask アプリ基盤 (ファクトリ, CORS, セキュリティヘッダ, リクエストコンテキスト)
```

## リポジトリとデプロイ

- プライマリリポジトリは GitLab (`gitlab.green-rabbit.net`)。push すると GitHub (`github.com/kimata/price-platform`) に自動同期される。
- 利用側アプリケーションは GitHub URL + コミットハッシュで依存を固定する:
  ```
  "price-platform @ git+https://github.com/kimata/price-platform@<commit-hash>"
  ```
- このライブラリを更新した後は、利用側アプリケーションの `pyproject.toml` のハッシュも更新する。

## 重要な注意事項

### 共通運用ルール

- 変更前に意図と影響範囲を説明し、ユーザー確認を取る
- `my_lib` の変更は `../my-py-lib` で実施し、利用側リポジトリのハッシュ更新後に `uv lock && uv sync` を実行
- 依存関係管理は `uv` を標準とし、他の手段はフォールバック扱い
- ミラー運用があるため、push は primary リポジトリ（GitLab）にのみ行う

### コード変更時のドキュメント更新

コードを更新した際は、以下のドキュメントも更新が必要か**必ず検討してください**:

| ドキュメント | 更新が必要なケース                                                 |
| ------------ | ------------------------------------------------------------------ |
| README.md    | 機能追加・変更、使用方法の変更、依存関係の変更                     |
| CLAUDE.md    | アーキテクチャ変更、新規モジュール追加、設定項目変更、開発手順変更 |

### バグ修正の原則

- 憶測に基づいて修正しないこと
- 必ず原因を論理的に確定させた上で修正すること
- 「念のため」の修正でコードを複雑化させないこと

### コード修正時の確認事項

- 関連するテストも修正すること
- 関連するドキュメントも更新すること

## 開発環境

### パッケージ管理

- **パッケージマネージャー**: uv
- **依存関係のインストール**: `uv sync`
- **依存関係の更新**: `uv lock --upgrade-package <package-name>`

## 開発ガイドライン

- `my_lib` は利用側アプリケーション群が共有する別の内部ライブラリ。config/loader.py と config/models.py が依存している。
- テストでは外部依存 (ファイルシステム等) の注入を可能にする設計を心がける (例: `now_fn` パラメータ)。
- セキュリティに関わるコード (secrets, password_hash, rate_limiter) は特に慎重にレビューする。

## コーディング規約

- Python 3.12+
- 型ヒントを積極的に使用
- dataclass で不変オブジェクトを定義（`frozen=True`）
- ruff でフォーマット・lint
- `except Exception` は避け、具体的な例外型を指定する
- 構造化データは `@dataclass` を優先し、辞書からの生成は `parse()` 命名で統一
- Union 型が 3 箇所以上で出現する場合は `TypeAlias` を定義

### インポートスタイル

`from xxx import yyy` は基本的に使わず、`import yyy` としてモジュールをインポートし、使用時は `yyy.xxx` の形式で参照する。

```python
# Good
import my_lib.selenium_util
my_lib.selenium_util.get_driver()

# Avoid
from my_lib.selenium_util import get_driver
get_driver()
```

**例外:**

- 標準ライブラリの一般的なパターン（例: `from pathlib import Path`）
- 型ヒント用のインポート（`from typing import TYPE_CHECKING`）
- dataclass などのデコレータ（`from dataclasses import dataclass`）

### 型チェック

型チェッカーのエラー対策として、各行に `# type: ignore` コメントを付けて回避するのは**最後の手段**とする。

基本方針:

1. **型推論が効くようにコードを書く** - 明示的な型注釈や適切な変数の初期化で対応
2. **型の絞り込み（Type Narrowing）を活用** - `assert`, `if`, `isinstance()` 等で型を絞り込む
3. **どうしても回避できない場合のみ `# type: ignore`** - その場合は理由をコメントに記載

### dataclass 優先

辞書（`dict[str, Any]`）よりも dataclass を優先する。特に:

- 複数の関数間で受け渡されるデータ構造
- 型安全性が重要なケース
- 属性アクセスが頻繁なケース

**ポイント:**

- 不変データには `frozen=True` を使用
- デフォルト値は `field(default=...)` または直接指定
- Union 型は `TypeA | TypeB` 形式で定義

### PEP 8 準拠

#### コレクションの空チェック

`len()` を使った比較ではなく、bool 評価を使用する:

```python
# Good
if not items:
    return

# Avoid
if len(items) == 0:
    return
```

### match 文の活用

`isinstance()` チェックよりも `match` 文を優先する（Python 3.10+）。

### functools の活用

手動でキャッシュを実装するのではなく、標準ライブラリの `lru_cache` 等を活用する。

### パス管理

- スキーマファイルや設定ファイルへのパスは、相対パスではなく `pathlib.Path(__file__)` を基準とした絶対パスを使用する
- ファイルパスを関数やクラスの引数として受け取る場合は `pathlib.Path` 型で統一し、文字列での受け渡しは避ける

### 返り値の型

関数の返り値に `dict[str, Any]` を使用せず、dataclass を定義して型安全性を確保する。
