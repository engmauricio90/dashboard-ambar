import io
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from scripts.backup_database import build_backup_path, run_pg_dump
from scripts.backup_media import build_archive_path, create_media_archive


class BackupScriptsTests(SimpleTestCase):
    def test_build_backup_path_uses_timestamp(self):
        now = datetime(2026, 9, 9, 12, 30, 5, tzinfo=timezone.utc)

        path = build_backup_path('backups/database', now=now)

        self.assertEqual(path, Path('backups/database/dashboard-db-20260909-123005.dump'))

    def test_database_backup_requires_database_url(self):
        with self.assertRaisesMessage(RuntimeError, 'DATABASE_URL nao configurada.'):
            run_pg_dump('', Path('backup.dump'))

    @mock.patch('scripts.backup_database.subprocess.run')
    @mock.patch('scripts.backup_database.shutil.which')
    def test_database_backup_does_not_print_or_log_database_url(self, mocked_which, mocked_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / 'db.dump'

            def fake_run(command, **kwargs):
                if command[0] == 'pg_dump':
                    Path(command[5]).write_bytes(b'PGDMP')
                return mock.Mock(returncode=0, stdout='', stderr='')

            mocked_which.return_value = '/usr/bin/tool'
            mocked_run.side_effect = fake_run

            result = run_pg_dump('postgres://user:secret@example/db', output)

        self.assertEqual(result['validation'], 'pg_restore --list')
        calls = [' '.join(call.args[0]) for call in mocked_run.call_args_list]
        self.assertIn('postgres://user:secret@example/db', calls[0])
        self.assertNotIn('postgres://user:secret@example/db', str(result))

    def test_build_archive_path_uses_timestamp(self):
        now = datetime(2026, 9, 9, 12, 30, 5, tzinfo=timezone.utc)

        path = build_archive_path('backups/media', now=now)

        self.assertEqual(path, Path('backups/media/dashboard-media-20260909-123005.tar.gz'))

    def test_media_archive_contains_media_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / 'media'
            root.mkdir()
            (root / 'foto.txt').write_text('conteudo', encoding='utf-8')
            output = Path(tmpdir) / 'backup.tar.gz'

            result = create_media_archive(root, output)

            self.assertGreater(result['bytes'], 0)
            with tarfile.open(output, 'r:gz') as archive:
                names = archive.getnames()

        self.assertIn('media/foto.txt', names)

    def test_media_archive_rejects_missing_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / 'missing'
            output = Path(tmpdir) / 'backup.tar.gz'

            with self.assertRaisesMessage(RuntimeError, 'MEDIA_ROOT invalido'):
                create_media_archive(missing, output)

            self.assertFalse(output.exists())
