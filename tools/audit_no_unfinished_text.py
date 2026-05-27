from __future__ import annotations
import argparse
from pathlib import Path

BLOCKED_PHRASES = ['coming soon', '_comingSoon', 'se activará pronto', 'fetched later', 'break later', 'added later', 'demo product', 'test product']
FALSE_POSITIVE = [
    'notification',
    'notifications',
    'not found',
    'notfound',
    'not interested',
    'notInterested',
    'fake_discount',
    'FakeDiscount',
    'BAD_TEXT',
    'low_title for bad',
]
EXT = {'.dart', '.py'}

def skip(line: str) -> bool:
    low = line.lower()
    return any(x.lower() in low for x in FALSE_POSITIVE)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    hits = []
    for file in root.rglob('*'):
        if file.suffix not in EXT:
            continue
        if any(p in {'.git','build','.dart_tool','__pycache__'} for p in file.parts):
            continue
        txt = file.read_text(encoding='utf-8', errors='ignore').splitlines()
        for i,line in enumerate(txt, 1):
            if skip(line): continue
            low=line.lower()
            for phrase in BLOCKED_PHRASES:
                if phrase.lower() in low:
                    hits.append((file, i, phrase, line.strip()))
    if hits:
        print('UNFINISHED TEXT FOUND')
        for file,i,phrase,line in hits:
            print(f'{file}:{i}: [{phrase}] {line}')
        raise SystemExit(1)
    print('OK: no blocked unfinished text found')
if __name__ == '__main__': main()
