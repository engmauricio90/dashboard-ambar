import argparse
import os
import tarfile
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_archive_path(output_dir, prefix='dashboard-media', now=None):
    timestamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%d-%H%M%S')
    return Path(output_dir) / f'{prefix}-{timestamp}.tar.gz'


def create_media_archive(media_root, output_path):
    media_root = Path(media_root)
    if not media_root.exists() or not media_root.is_dir():
        raise RuntimeError(f'MEDIA_ROOT invalido ou inexistente: {media_root}')

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=output_path.name, suffix='.tmp', dir=output_path.parent, delete=False) as handle:
        temp_path = Path(handle.name)

    try:
        with tarfile.open(temp_path, 'w:gz') as archive:
            archive.add(media_root, arcname='media')
        if temp_path.stat().st_size == 0:
            raise RuntimeError('Arquivo de backup de media ficou vazio.')
        with tarfile.open(temp_path, 'r:gz') as archive:
            archive.getmembers()
        temp_path.replace(output_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    return {'path': output_path, 'bytes': output_path.stat().st_size}


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Gera archive tar.gz de MEDIA_ROOT sem apagar a origem.')
    parser.add_argument('--media-root', default=os.environ.get('MEDIA_ROOT') or os.environ.get('DJANGO_MEDIA_ROOT') or 'media')
    parser.add_argument('--output-dir', default='backups/media')
    parser.add_argument('--prefix', default='dashboard-media')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    output_path = build_archive_path(args.output_dir, args.prefix)
    result = create_media_archive(args.media_root, output_path)
    print(f'Backup de media criado: {result["path"]}')
    print(f'Tamanho: {result["bytes"]} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
