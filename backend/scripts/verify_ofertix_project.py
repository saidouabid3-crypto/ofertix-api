from __future__ import annotations

import json
import os
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLUTTER_ROOT = ROOT.parent
LANG_DIR = FLUTTER_ROOT / 'assets' / 'lang'

BACKEND_FILES = [
    ROOT / 'main.py',
    ROOT / 'routes' / 'products.py',
    ROOT / 'routes' / 'home_feed.py',
    ROOT / 'services' / 'home_feed_service.py',
    ROOT / 'utils' / 'product_standard.py',
    ROOT / 'utils' / 'product_normalizer.py',
    ROOT / 'scripts' / 'normalize_existing_products.py',
]


def check_compile() -> list[str]:
    errors = []
    for file in BACKEND_FILES:
        if not file.exists():
            errors.append(f'MISSING backend file: {file.relative_to(ROOT)}')
            continue
        try:
            py_compile.compile(str(file), doraise=True)
        except Exception as exc:
            errors.append(f'COMPILE ERROR {file.relative_to(ROOT)}: {exc}')
    return errors


def check_lang() -> list[str]:
    warnings = []
    if not LANG_DIR.exists():
        return [f'LANG folder not found: {LANG_DIR}']
    data = {}
    for file in LANG_DIR.glob('*.json'):
        data[file.stem] = json.loads(file.read_text(encoding='utf-8'))
    if not data:
        return ['No language json files found']
    all_keys = set().union(*(set(v.keys()) for v in data.values()))
    for lang, values in sorted(data.items()):
        missing = sorted(all_keys - set(values.keys()))
        if missing:
            warnings.append(f'{lang}: missing {len(missing)} keys, first: {missing[:10]}')
    return warnings


def check_secrets() -> list[str]:
    warnings = []
    for name in ['.env', 'firebase_key.json']:
        if (ROOT / name).exists():
            warnings.append(f'LOCAL SECRET PRESENT (ok locally, do not push): backend/{name}')
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8') if (ROOT / '.gitignore').exists() else ''
    for required in ['.env', 'firebase_key.json', 'data/', '__pycache__']:
        if required not in gitignore:
            warnings.append(f'.gitignore should contain: {required}')
    return warnings


def main():
    errors = []
    warnings = []
    errors += check_compile()
    warnings += check_lang()
    warnings += check_secrets()
    print('OFERTIX VERIFICATION REPORT')
    print('Backend root:', ROOT)
    print('Flutter root:', FLUTTER_ROOT)
    if errors:
        print('\nERRORS:')
        for e in errors:
            print('❌', e)
    else:
        print('\n✅ Backend compile: OK')
    if warnings:
        print('\nWARNINGS:')
        for w in warnings:
            print('⚠️', w)
    else:
        print('✅ Language keys and gitignore: OK')
    print('\nNEXT REQUIRED LOCAL CHECKS:')
    print('flutter clean')
    print('flutter pub get')
    print('flutter analyze')
    print('flutter run')
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
