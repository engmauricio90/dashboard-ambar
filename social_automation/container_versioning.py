from hashlib import sha256
import logging


logger = logging.getLogger(__name__)
REEL_SHARE_TO_FEED = 'true'


def build_instagram_caption(content):
    partes = []
    if content.legenda:
        partes.append(content.legenda.strip())
    if content.hashtags:
        hashtags = []
        for item in content.hashtags.replace('\n', ' ').split():
            tag = item.strip()
            if not tag:
                continue
            hashtags.append('#' + tag.lstrip('#'))
        if hashtags:
            partes.append(' '.join(dict.fromkeys(hashtags)))
    return '\n\n'.join(partes)


def _media_field(content):
    return content.final_video if content.is_reel else content.final_image


def calculate_social_media_hash(content):
    media = _media_field(content)
    if not media:
        return ''
    hasher = sha256()
    with media.storage.open(media.name, 'rb') as arquivo:
        for chunk in iter(lambda: arquivo.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def calculate_instagram_container_fingerprint(content):
    media_hash = calculate_social_media_hash(content)
    caption = build_instagram_caption(content)
    share_to_feed = REEL_SHARE_TO_FEED if content.is_reel else ''
    payload = '\n'.join(
        [
            f'media_sha256={media_hash}',
            f'media_type={content.media_type}',
            f'caption={caption}',
            f'share_to_feed={share_to_feed}',
        ]
    )
    return sha256(payload.encode('utf-8')).hexdigest()


def invalidate_instagram_container(content, *, reason='media_changed', save=True):
    if not content.instagram_container_id and not content.instagram_container_fingerprint:
        return False
    old_container_id = content.instagram_container_id
    old_fingerprint = content.instagram_container_fingerprint
    content.instagram_container_id = ''
    content.instagram_container_fingerprint = ''
    if save:
        content.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
    logger.info(
        'instagram_container_invalidated content_id=%s media_type=%s container_id=%s fingerprint_prefix=%s reason=%s',
        content.id,
        content.media_type,
        old_container_id,
        (old_fingerprint or '')[:12],
        reason,
    )
    return True
