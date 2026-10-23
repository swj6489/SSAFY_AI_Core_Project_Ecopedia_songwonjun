"""실행 비밀·캐시·가상환경을 제외한 소스 패키지 생성."""
import re
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def main():
    top = ['app.py', 'config.json', 'requirements.txt', 'README.md', 'run.ps1', '.env.example', '.gitignore']
    files = [ROOT / name for name in top]
    for folder in ['ecopedia', 'data', 'docs', 'scripts', 'tests', '.streamlit']:
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix in ('.py', '.json', '.md', '.toml'))
    environment = dotenv_values(ROOT / '.env') if (ROOT / '.env').exists() else {}
    secrets = [environment.get('OPENAI_API_KEY', ''), environment.get('GMS_KEY', '')]
    secrets += re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', environment.get('WIKIMEDIA_USER_AGENT', '') or '')
    secrets = [s.encode('utf-8') for s in secrets if s]
    for path in files:
        body = path.read_bytes()
        if any(secret in body for secret in secrets):
            raise RuntimeError(f'비밀 정보가 포함되어 패키지 생성을 중단했습니다: {path.name}')
    target = ROOT.parent / 'EcoPedia_코드.zip'
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path, Path('ecopedia') / path.relative_to(ROOT))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert not any(Path(name).name == '.env' for name in archive.namelist())
        assert all(not any(secret in archive.read(name) for secret in secrets) for name in archive.namelist())
        print(f'Packaged {len(archive.namelist())} files; credential/email scan passed.')
    print(target)


if __name__ == '__main__':
    main()
