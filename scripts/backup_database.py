import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_backup_path(output_dir, prefix='dashboard-db', now=None):
    timestamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%d-%H%M%S')
    return Path(output_dir) / f'{prefix}-{timestamp}.dump'


def run_pg_dump(database_url, output_path, pg_dump='pg_dump', pg_restore='pg_restore'):
    if not database_url:
        raise RuntimeError('DATABASE_URL nao configurada.')
    if shutil.which(pg_dump) is None:
        raise RuntimeError(f'{pg_dump} nao encontrado no PATH.')

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    if temp_path.exists():
        temp_path.unlink()

    command = [pg_dump, '--format=custom', '--no-owner', '--no-acl', '--file', str(temp_path), database_url]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError('pg_dump falhou.')

    if not temp_path.exists() or temp_path.stat().st_size == 0:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError('Dump gerado vazio ou inexistente.')

    validation = 'size'
    if shutil.which(pg_restore) is not None:
        validate = subprocess.run([pg_restore, '--list', str(temp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if validate.returncode != 0:
            temp_path.unlink()
            raise RuntimeError('pg_restore --list nao conseguiu validar o dump.')
        validation = 'pg_restore --list'

    temp_path.replace(output_path)
    return {'path': output_path, 'bytes': output_path.stat().st_size, 'validation': validation}


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Gera backup PostgreSQL em formato custom sem imprimir credenciais.')
    parser.add_argument('--output-dir', default='backups/database')
    parser.add_argument('--database-url-env', default='DATABASE_URL')
    parser.add_argument('--prefix', default='dashboard-db')
    parser.add_argument('--pg-dump', default='pg_dump')
    parser.add_argument('--pg-restore', default='pg_restore')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    output_path = build_backup_path(args.output_dir, args.prefix)
    result = run_pg_dump(
        os.environ.get(args.database_url_env, ''),
        output_path,
        pg_dump=args.pg_dump,
        pg_restore=args.pg_restore,
    )
    print(f'Backup PostgreSQL criado: {result["path"]}')
    print(f'Tamanho: {result["bytes"]} bytes')
    print(f'Validacao: {result["validation"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
