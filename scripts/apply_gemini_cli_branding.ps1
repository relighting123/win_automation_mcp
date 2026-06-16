# gemini-cli 소스에 chatRTD 브랜딩 패치 적용 후 로컬 빌드
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Patch = Join-Path $Root "patches\gemini-cli\chatrtd-branding.patch"
$Target = if ($env:GEMINI_CLI_SRC) { $env:GEMINI_CLI_SRC } else { Join-Path (Split-Path $Root -Parent) "gemini-cli" }

if (-not (Test-Path (Join-Path $Target ".git"))) {
    Write-Host "[info] gemini-cli 클론: $Target"
    git clone --depth 1 https://github.com/google-gemini/gemini-cli.git $Target
}

Push-Location $Target
try {
    git checkout -- packages/cli/src/ui/components/AppHeader.tsx `
        packages/cli/src/ui/components/AsciiArt.ts `
        packages/cli/src/utils/windowTitle.ts 2>$null

    Write-Host "[info] 패치 적용"
    git apply $Patch

    Write-Host "[info] 빌드 (npm install && npm run build)"
    npm install
    npm run build

    Write-Host ""
    Write-Host "[ok] 완료. 아래처럼 실행하세요:"
    Write-Host "  `$env:CHATRTD_GEMINI_BRANDED = '1'"
    Write-Host "  `$env:Path = `"$Target\packages\cli\bin;`$env:Path`""
    Write-Host "  python `"$Root\scripts\start_chatrtd_gemini.py`""
}
finally {
    Pop-Location
}
