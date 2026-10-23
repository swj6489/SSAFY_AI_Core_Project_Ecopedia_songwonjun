$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    Write-Host 'Python 가상환경을 만듭니다.'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '가상환경 생성에 실패했습니다.' }
}
& $taskPython -c 'import streamlit, chromadb, langgraph'
if ($LASTEXITCODE -ne 0) {
    & $taskPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '패키지 설치에 실패했습니다.' }
}
& $taskPython -m streamlit run app.py
