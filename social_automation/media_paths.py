import posixpath
import re
from pathlib import PurePosixPath
from uuid import uuid4


SOCIAL_ROOT = 'social'
INVALID_PATH_MARKERS = {'', '.', '..'}


def safe_media_filename(filename, *, default_extension='.jpg'):
    raw = str(filename or '').replace('\\', '/').strip()
    if not raw:
        raw = f'{uuid4().hex}{default_extension}'
    name = PurePosixPath(raw).name
    if not name or name in INVALID_PATH_MARKERS:
        name = f'{uuid4().hex}{default_extension}'
    stem, ext = posixpath.splitext(name)
    ext = ext.lower() or default_extension
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', stem).strip('.-_')
    if not stem:
        stem = uuid4().hex
    return f'{stem}{ext}'


def unique_media_filename(extension='.jpg'):
    extension = extension if str(extension).startswith('.') else f'.{extension}'
    return f'{uuid4().hex}{extension.lower()}'


def social_storage_path(profile_id, *parts, filename, default_extension='.jpg'):
    profile = str(profile_id or 'sem-perfil')
    clean_parts = [
        str(part).replace('\\', '/').strip('/ ')
        for part in parts
        if str(part or '').strip('/ ')
    ]
    clean_parts = [part for part in clean_parts if part not in INVALID_PATH_MARKERS and '..' not in part.split('/')]
    name = safe_media_filename(filename, default_extension=default_extension)
    return posixpath.join(SOCIAL_ROOT, profile, *clean_parts, name)


def social_upload_to(profile_id, directory, filename, *, default_extension='.jpg'):
    return social_storage_path(profile_id, directory, filename=filename, default_extension=default_extension)


def classify_social_media_path(stored_name, *, expected_profile_id=None):
    name = str(stored_name or '').replace('\\', '/')
    if not name:
        return 'empty'
    if re.match(r'^[A-Za-z]:/', name) or name.startswith('/'):
        return 'absolute'
    parts = [part for part in name.split('/') if part]
    if '..' in parts:
        return 'other_invalid'
    if len(parts) < 3 or parts[0] != SOCIAL_ROOT:
        return 'other_invalid'
    duplicated = any(
        parts[index : index + 2] == [SOCIAL_ROOT, parts[1]]
        for index in range(2, len(parts) - 1)
    )
    if duplicated:
        return 'duplicated_prefix'
    if expected_profile_id is not None and str(parts[1]) != str(expected_profile_id):
        return 'cross_profile_suspect'
    return 'canonical'
