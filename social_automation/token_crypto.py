from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class InstagramTokenEncryptionError(Exception):
    pass


def _fernet():
    raw_key = (settings.SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY or '').strip()

    if not raw_key:
        raise InstagramTokenEncryptionError(
            'SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY nao configurada.'
        )

    try:
        return Fernet(raw_key.encode('utf-8'))
    except Exception as exc:
        raise InstagramTokenEncryptionError(
            'Chave de criptografia do Instagram invalida.'
        ) from exc


def encrypt_instagram_token(token):
    token = str(token or '').strip()

    if not token:
        raise InstagramTokenEncryptionError('Token Instagram vazio.')

    return _fernet().encrypt(
        token.encode('utf-8')
    ).decode('utf-8')


def decrypt_instagram_token(encrypted_token):
    encrypted_token = str(encrypted_token or '').strip()

    if not encrypted_token:
        raise InstagramTokenEncryptionError(
            'Token Instagram nao configurado.'
        )

    try:
        return _fernet().decrypt(
            encrypted_token.encode('utf-8')
        ).decode('utf-8')
    except InvalidToken as exc:
        raise InstagramTokenEncryptionError(
            'Token Instagram nao pode ser descriptografado.'
        ) from exc
