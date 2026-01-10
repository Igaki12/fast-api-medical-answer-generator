# AGENTS_for_React.md
（同一ドメイン配信 / FastAPI + React / legacy pipeline 対応）

このドキュメントは、既存の FastAPI（legacy pipeline API）と同一ディレクトリ（同一リポジトリ）で **React フロントエンドを追加し、同一ドメインで配信**するための実装・運用指針をまとめたものです。  
React からの API 呼び出しは `fetch()` を使用し、ジョブ開始後は `job_id` を保持して `status` 確認・`download` を行います。  
プロトタイプ段階では、**`multipart/form-data` の `api_key` を送信可能** とするため、フロントからも `api_key` を送れる前提で設計します。
(ただし、最終的には外部LLMのAPIキーはサーバ側で管理する方針です)

---

## 0. 前提とゴール

### 前提
- 既存 FastAPI が動作している（例：`uvicorn ... --port 8000`）
- React は **同一ドメイン**で静的配信する（例：`https://example.com/`）
- API は **同一ドメインの `/api/...`** で提供する（例：`https://example.com/api/v1/...`）
- 本番は Nginx または Apache を前段に置き、
  - `/` → React 静的ファイル
  - `/api/` → FastAPI へリバースプロキシ
- CORS は「同一オリジン運用」では **原則不要**（開発時だけ必要ならプロキシで回避）

### ゴール
- React の SPA（シングルページアプリ）を導入
- API とフロントのパス衝突を避ける（`/api` をバックエンド専用に固定）
- `fetch("/api/...")` だけで dev/prod ともに動く構成

---

## 1. リポジトリ / ディレクトリ構成（推奨）

既存 FastAPI と同じディレクトリ（同一 repo 直下）に `frontend/` を追加します。  
このリポジトリの現状に合わせると、以下のような構成になります（`frontend/` と `deploy/` が追加分）。

```
fast-api-medical-answer-generator/
├──AGENTS.md
├──AGENTS_for_React.md
├──AGENTS_for_legacy_scripts.md
├──README.md
├──main.py
├──requirements-min.txt
├──app/
│  ├──auth.py
│  ├──models.py
│  └──services/
│     ├──generator.py
│     ├──file_manager.py
│     └──legacy/
│        ├──convert_markdown.py
│        ├──generate_markdown.py
│        ├──pipeline.py
│        └──pandoc-header-v1.0.tex
├──legacy_scripts/
├──references/
├──data/
│   ├──inputs/
│   └──outputs/
├──frontend/             # 追加: React (Vite想定)
│   ├──src/
│   ├──public/
│   ├──package.json
│   └──vite.config.ts
└──deploy/               # 追加: Nginx/Apacheの設定サンプル（任意）
    └──nginx/ or apache/
```

> 既存構造は `main.py` + `app/` 直下で FastAPI を動かす構成です。  
> 重要なのは「React の成果物(dist)」を Web サーバが配信できる位置に置くことです。

---

## 2. ルーティング設計（衝突回避のルール）

### 2.1 パス予約
- **`/api` はバックエンド専用**（React 側ルーティングでは使わない）
- React の SPA ルートは `/` 配下（例：`/`, `/jobs`, `/settings` など）

### 2.2 SPA のフォールバック
React Router 等を使う場合は、`/jobs` のような直アクセスが 404 にならないように、Web サーバ側で **`index.html` にフォールバック**させます。

---

## 3. CORS 方針（同一ドメイン前提）

### 3.1 本番（同一オリジン）
- `https://example.com` から `https://example.com/api/...` を呼ぶので **CORSは不要**
- FastAPI に CORS ミドルウェアは付けなくても動きます（付けるなら「無駄に広げない」）

### 3.2 開発（React dev server が別ポートになる場合）
- React: `http://localhost:5173`
- API: `http://localhost:8000`
のように別オリジンになるため、Viteのdev proxyで対処します。

**推奨：Vite の dev proxy を使い、CORSを回避**（本番と同じ `/api` で書ける）

`frontend/vite.config.ts`（例）:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
```

> これで React 側は `fetch("/api/...")` のままで OK。  
> FastAPI 側で CORS を緩める必要がありません。

---

## 4. API 呼び出しの統一ルール（fetch）

### 4.1 ベースURLは必ず相対パス
- **禁止**：`fetch("http://localhost:8000/api/...")` の直書き
- **推奨**：`fetch("/api/v1/...")`（相対パス固定）

### 4.2 fetch ラッパ（推奨）
`frontend/src/lib/api.ts`（例）:
```ts
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
    },
  });

  // 失敗時は統一して投げる（UIで表示）
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API Error: ${res.status} ${res.statusText} ${text}`);
  }

  // ダウンロード系は別関数で扱う
  return (await res.json()) as T;
}
```

---

## 5. ジョブ実行フロー（legacy pipeline）

React 側は次のステートを持ちます（AGENTS.md準拠）。
- `jobId: string`
- `status: "queued" | "generating_md" | "generating_pdf" | "done" | "failed" | "failed_to_convert" | "expired" | ...`
- `progress?: number`（もしAPIが返すなら）
- `message?: string` / `error?: string`

### 5.1 ジョブ開始（upload / start）
例：`POST /api/v1/pipeline`  
`multipart/form-data` で PDF 等とメタデータを送信します。  
`api_key` は **任意**（未指定時はサーバー環境変数へフォールバック）。

```ts
type StartLegacyPipelineParams = {
  apiKey?: string;
  file: File;
  explanationName: string;
  university: string;
  year: string;
  subject: string;
  author: string;
};

export async function startLegacyPipeline(params: StartLegacyPipelineParams) {
  const fd = new FormData();
  if (params.apiKey) fd.append("api_key", params.apiKey);
  fd.append("input_file", params.file);
  fd.append("explanation_name", params.explanationName);
  fd.append("university", params.university);
  fd.append("year", params.year);
  fd.append("subject", params.subject);
  fd.append("author", params.author);

  return apiFetch<{ job_id: string }>(
    "/api/v1/pipeline",
    { method: "POST", body: fd },
  );
}
```

### 5.2 ステータス確認（polling）
例：`GET /api/v1/pipeline/{job_id}`  
一定間隔でポーリングします（例：10秒）。

```ts
export async function getJobStatus(jobId: string) {
  return apiFetch<{ status: string; message?: string; error?: string }>(
    `/api/v1/pipeline/${encodeURIComponent(jobId)}`
  );
}
```

**UI実装のポイント**
- `setInterval` より `setTimeout` で逐次ポーリング（状態に応じて間隔調整しやすい）
- 画面遷移/アンマウント時に `AbortController` で止める
- 失敗時は `detail` / `error` を画面に出す（問い合わせに必要）
- `failed_to_convert`（生成時のPDF変換失敗）または `generating_md` が30分以上続く場合は「もう一度試す」を表示して再送信できるようにする
- 通知は `useToast()` に統一して、フォーム下のテキスト表示は使わない

### 5.3 ダウンロード（PDF）
例：`GET /api/v1/pipeline/{job_id}/download`  
`fetch` + `Blob` で保存します。
PDF変換に失敗した場合は `409 Conflict` が返るため、UI側で再試行導線を出す。

**UI実装のポイント**
- `Content-Disposition` のファイル名を優先して `.pdf` で保存する

```ts
export async function downloadResult(jobId: string) {
  const res = await fetch(
    `/api/v1/pipeline/${encodeURIComponent(jobId)}/download`
  );
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `result_${jobId}.pdf`; // 返却ヘッダContent-Dispositionがあればそれ優先でもOK
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
}
```

---

### 5.4 WebStorage でのジョブ管理（APIアクセス削減）
- `localStorage` に `job_id` と `status`、`explanation_name`、`created_at`、`updated_at` を保存
- 入力フォームの `year` / `subject` / `university` / `author` / `explanation_name` も保存して再入力を省略
- 画面ロード時は **WebStorage → 画面表示** を優先し、最新化が必要なジョブのみAPIで確認
- ポーリング対象は `queued` / `generating_md` のみ（`done`/`failed` は一定時間後に再チェック）
- 例: `localStorage["pipeline_jobs"]` に配列で保持

---

## 5.5 UI/UX デザイン仕様（React + Vite + Chakra UI）

### 5.5.1 画面全体の方向性
- **テーマ**: 白 + ゴールド基調の高級感（暖色寄りの金、白は温かみ寄り）
- **タイポグラフィ**: 見出しはセリフ系、本文は読みやすいサンセリフでコントラストを付ける
- **背景**: 単色ではなく、薄いグラデーション + 金色のハイライト形状（ぼかし）
- **レスポンシブ**: スマホ/タブレット/デスクトップで 1カラム → 2カラムの切替

### 5.5.2 コンポーネント構成（上→下）
1. **APIリクエストカード（最上部）**
   - 目的: 新しい生成リクエストの入力
   - 内容:
     - 注意書き（生成AIの限界・利用責任）
     - 入力欄:
       - `api_key`（任意）
       - `year`, `subject`, `university`, `author`, `input_file`
       - `explanation_name` は **自動提案**（`year + subject + "_解答解説"`）
         - 手動編集可（自動提案は初期値のみ）
     - ボタン: **「リクエストする」**
   - **TIPSは常時表示**（アニメーションでカルーセル表示）:
     - 「最大15分程度待つ可能性」
     - 「大きいファイル/多数の画像で失敗する可能性」
     - 「失敗時は分割して再実行すると成功する場合がある」

2. **ジョブ一覧（job_idごとのカードが縦に並ぶ）**
   - 各カードに表示:
     - `job_id`
   - `status`（日本語表示）
   - `explanation_name`
   - `created_at` / `updated_at`
   - `queued` / `generating_md` / `generating_pdf` の場合は残り時間の目安を表示
   - `status == done` なら「ダウンロードする」ボタンを表示
   - `failed_to_convert` または `generating_md` が30分以上続く場合は「もう一度試す」ボタンを表示
   - ダウンロード中は **カード全体にオーバーレイ表示**（後述）
   - ジョブ検索で追加された job は `explanation_name` が不明な場合 `job_id` を表示名として使う

3. **ジョブ検索（一覧の下）**
   - `job_id` を入力して `status` を取得できた場合のみ一覧に追加
   - 追加操作は「＋ 追加」ボタンで明示する

### 5.5.3 Chakra UI スタイルの具体化
- **カラーパレット**
  - `bg`: #F7F4EE
  - `gold`: #C9A14A
  - `goldDeep`: #8C6A1F
  - `ink`: #1E1B16
  - `muted`: #6D5F4B
- **フォント**
  - 見出し: `"Cinzel", serif`
  - 本文: `"Source Sans 3", sans-serif`
  - Chakra の `extendTheme` で global 指定
- **カード**
  - 白背景 + 金色のボーダー（薄め）
  - シャドウは柔らかく、ホバーでわずかに浮く
- **入力フォーム**
  - `FormLabel` を大きめに
  - フォーカス時の `outlineColor` は `gold`

### 5.5.4 アニメーション指針
- **TIPS アニメーション**
  - ページ表示時から常時表示
  - フェードイン + 上方向にゆっくりスライド
  - 数秒ごとに内容が切り替わるカルーセル
- **ダウンロード中アニメーション**
  - カード全体にオーバーレイ（透明度 60〜70%）
  - ゴールドの点が横移動するローディングバー
  - 2〜4秒ごとに形が変わる（円→菱形→線）

### 5.5.5 レスポンシブ挙動
- **スマホ**: 1カラム、フォームは縦積み、ジョブカードは全幅
- **タブレット**: 上部カードは横2カラム（入力欄を2列）
- **PC**: 上部カードは 2カラム + ジョブ一覧は2列グリッド

### 5.5.6 実装メモ（Chakra UI）
- `Grid` + `GridItem` を使い、ブレークポイントで列数切り替え
- `useToast` は使用せず、TIPSは専用カードに表示（視認性優先）
- TIPS の内容切替は `Fade` / `SlideFade` などで軽く動かす

### 5.5.7 ステータスの日本語表示（UI側マッピング）
- `queued`: 受付済み
- `generating_md`: Markdown 生成中
- `done`: 完了
- `failed`: 失敗
- `failed_to_convert`: PDF変換失敗（Markdownのみ）
- `expired`: 期限切れ

---

## 6. Webサーバ（Nginx / Apache）接続設計（同一ドメイン）

### 6.1 原則
- **React は静的ファイルとして配信**（`frontend/dist/`）
- **`/api/` は FastAPI にプロキシ**
- SPA ルーティングのために `/` 配下は **`index.html` フォールバック**

---

### 6.2 Nginx 設定例（推奨）
`/var/www/app/dist` に React のビルド成果物を置く想定です。

```nginx
server {
  listen 443 ssl;
  server_name example.com;

  # React (Vite build) dist
  root /var/www/app/dist;
  index index.html;

  # API -> FastAPI
  location /api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # アップロードがあるなら大きめに（要調整）
    client_max_body_size 50m;
    proxy_read_timeout 300;
  }

  # SPA fallback
  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

ポイント
- `location /api/` を先に書く（`/` の fallback に飲まれないように）
- `client_max_body_size` と `proxy_read_timeout` は pipeline の性質に合わせて調整
- 生成処理が長い場合、**APIは非同期ジョブ化**が前提（すでに job_id 運用なのでOK）

---

### 6.3 Apache 設定例（Proxy + SPA fallback）
Apache 2.4系想定。`DocumentRoot` を React の dist にします。

```apache
<VirtualHost *:443>
  ServerName example.com

  DocumentRoot "/var/www/app/dist"

  # API reverse proxy
  ProxyPreserveHost On
  ProxyPass "/api/" "http://127.0.0.1:8000/"
  ProxyPassReverse "/api/" "http://127.0.0.1:8000/"

  # Upload size (必要に応じて)
  LimitRequestBody 52428800

  # SPA fallback（React Router等）
  <Directory "/var/www/app/dist">
    Options -Indexes +FollowSymLinks
    AllowOverride None
    Require all granted
  </Directory>

  RewriteEngine On
  RewriteCond %{REQUEST_FILENAME} -f [OR]
  RewriteCond %{REQUEST_FILENAME} -d
  RewriteRule ^ - [L]

  # /api は除外（重要）
  RewriteCond %{REQUEST_URI} !^/api/
  RewriteRule ^ /index.html [L]
</VirtualHost>
```

---

## 7. ビルド / 配置手順（例）

### 7.1 React ビルド
```
cd frontend
npm ci
npm run build
```
成果物：`frontend/dist/`

### 7.2 配置（例）
- `frontend/dist/` をサーバの `DocumentRoot`（例：`/var/www/app/dist`）へ配置
- Nginx/Apache の設定で `/api` を FastAPI にプロキシ

> 同一リポジトリ内に置く場合でも、本番では「配信用ディレクトリ」は `/var/www/...` などに置く方が管理しやすいです。  
> ただし、運用ポリシーにより repo 直下 `frontend/dist` を直接配信しても構いません。

---

## 8. FastAPI 側（APIキーの扱い）

### 8.1 クライアントから `api_key` を受け取る前提（プロトタイプ）
- `multipart/form-data` の `api_key` を許可（`/api/v1/generate_explanation` は必須）
- legacy pipeline では `api_key` は任意、未指定時は環境変数にフォールバック
- 将来的にキーをサーバー側固定へ移行する場合は、React 側の入力を削除する

### 8.2 ログに秘匿情報を出さない
- リクエストログに Authorization / 外部キーが出ないよう注意
- 例外ログに “入力全文” を吐かない（PDF内容や個人情報の混入がある場合）

---

## 9. 先に決めておくと事故が減る仕様（推奨）

### 9.1 ジョブ状態（status）の列挙
- 例：`queued`, `running`, `converting`, `done`, `failed`, `expired`
- `failed` の場合は `error_code` と `detail` を返す（UI表示に必要）

### 9.2 保持期間・クリーンアップ
- 生成物 PDF / 中間成果物の保持時間（例：24h / 7d）
- 期限切れ `expired` の扱い（再実行導線、削除済み表示）

### 9.3 レート制限・同時実行
- 1ユーザーあたり同時ジョブ数（例：1〜3）
- 1IPあたりの開始回数（DoS対策）
- 20MBを超えるPDFの拒否・ファイル種別チェック

### 9.4 エラーの統一フォーマット
例（推奨）：
```json
{
  "error": {
    "code": "PIPELINE_TIMEOUT",
    "message": "Pipeline timed out",
    "detail": "pandoc took too long"
  }
}
```

---

## 10. 運用メモ（最低限）
- 本番は FastAPI を「直接インターネットに晒さない」
  - Nginx/Apache の背後（127.0.0.1:8000 等）で待ち受ける
- アップロードがあるので Webサーバ側のサイズ制限を必ず合わせる
- `download` は大きい可能性があるため、`proxy_read_timeout` やバッファ設定を必要に応じて調整

---

## 11. 実装チェックリスト

- [ ] React からの API 呼び出しは `fetch("/api/...")` のみ
- [ ] `/api` は Web サーバで FastAPI にプロキシされる
- [ ] SPA fallback があり、React Router の直アクセスで 404 にならない
- [ ] 開発時は Vite proxy で CORS を回避（または dev のみ CORS）
- [ ] job_id を保持して `status` ポーリング → `download` を実装
- [ ] `api_key` の扱いは AGENTS.md に合わせる（必須/任意/フォールバック）
