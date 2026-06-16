#!/usr/bin/env bash
# gemini-cli 소스에 chatRTD 브랜딩 패치 적용 후 로컬 빌드
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATCH="$ROOT/patches/gemini-cli/chatrtd-branding.patch"
TARGET="${GEMINI_CLI_SRC:-$ROOT/../gemini-cli}"

if [[ ! -d "$TARGET/.git" ]]; then
  echo "[info] gemini-cli 클론: $TARGET"
  git clone --depth 1 https://github.com/google-gemini/gemini-cli.git "$TARGET"
fi

cd "$TARGET"
git checkout -- packages/cli/src/ui/components/AppHeader.tsx \
  packages/cli/src/ui/components/AsciiArt.ts \
  packages/cli/src/utils/windowTitle.ts 2>/dev/null || true

echo "[info] 패치 적용"
git apply "$PATCH"

echo "[info] 빌드 (npm install && npm run build)"
npm install
npm run build

echo ""
echo "[ok] 완료. 아래처럼 실행하세요:"
echo "  export CHATRTD_GEMINI_BRANDED=1"
echo "  export PATH=\"$TARGET/packages/cli/bin:\$PATH\""
echo "  python \"$ROOT/scripts/start_chatrtd_gemini.py\""
