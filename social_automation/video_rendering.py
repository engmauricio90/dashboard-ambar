import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageFilter, ImageOps

from .media_paths import unique_media_filename
from .rendering import CANVAS_SIZE, SocialRenderError, _apply_gradient, _draw_text_box, _reel_text_boxes
from .typography import typography_for_identity
from .visual_composer import visual_identity_for_profile


REEL_SIZE = (1080, 1920)
REEL_FPS = 30
REEL_CODEC = 'h264'
logger = logging.getLogger(__name__)


class SocialVideoRenderError(SocialRenderError):
    pass


def ffmpeg_path():
    return shutil.which('ffmpeg')


def ffprobe_path():
    return shutil.which('ffprobe')


def _elapsed_ms(start):
    return int((time.monotonic() - start) * 1000)


def _sanitize_error(text):
    return str(text or '').replace('\\', '/')[-800:]


def _compose_reel_frame(content):
    if not content.base_image or not content.base_image.arquivo:
        raise SocialVideoRenderError('Selecione uma imagem-base antes de renderizar o Reel.')

    try:
        with content.base_image.arquivo.open('rb') as arquivo:
            image = Image.open(arquivo)
            image = ImageOps.exif_transpose(image).convert('RGB')
    except Exception as exc:
        raise SocialVideoRenderError('Nao foi possivel abrir a imagem-base para o Reel.') from exc

    background = ImageOps.fit(image, REEL_SIZE, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=18))
    dim = Image.new('RGBA', REEL_SIZE, (0, 0, 0, 92))
    frame = Image.alpha_composite(background.convert('RGBA'), dim)

    foreground = ImageOps.contain(image, (REEL_SIZE[0], 1280), method=Image.Resampling.LANCZOS).convert('RGBA')
    x = (REEL_SIZE[0] - foreground.width) // 2
    y = 170
    frame.alpha_composite(foreground, (x, y))

    boxes = []
    for box in _reel_text_boxes(content.base_image):
        region = box['region']
        source_canvas = box.get('source_canvas') or CANVAS_SIZE
        scale_x = REEL_SIZE[0] / source_canvas[0]
        scale_y = REEL_SIZE[1] / source_canvas[1]
        scaled = (
            round(region[0] * scale_x),
            round(region[1] * scale_y),
            round(region[2] * scale_x),
            round(region[3] * scale_y),
        )
        # Preserva margem de interface do Instagram.
        top_safe = 170
        bottom_safe = REEL_SIZE[1] - 230
        y0 = max(scaled[1], top_safe)
        y1 = min(scaled[1] + scaled[3], bottom_safe)
        boxes.append({**box, 'region': (scaled[0], y0, scaled[2], max(1, y1 - y0))})

    overlay = Image.new('RGBA', REEL_SIZE, (0, 0, 0, 0))
    typography = typography_for_identity(visual_identity_for_profile(content.profile), context='reel')
    last_error = None
    for box in boxes:
        box = {**box, 'typography': typography}
        candidate = Image.new('RGBA', REEL_SIZE, (0, 0, 0, 0))
        _apply_gradient(candidate, box['gradient_position'], box['region'])
        try:
            _draw_text_box(candidate, content.frase, box)
        except SocialRenderError as exc:
            last_error = exc
            continue
        overlay = candidate
        break
    else:
        raise last_error or SocialVideoRenderError('Texto grande demais para renderizar o Reel.')

    return Image.alpha_composite(frame, overlay).convert('RGB')


def _ffmpeg_command(ffmpeg, frame_path, output_path, duration):
    return [
        ffmpeg,
        '-hide_banner',
        '-loglevel',
        'error',
        '-loop',
        '1',
        '-framerate',
        str(REEL_FPS),
        '-i',
        str(frame_path),
        '-t',
        str(duration),
        '-r',
        str(REEL_FPS),
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-tune',
        'stillimage',
        '-pix_fmt',
        'yuv420p',
        '-threads',
        '1',
        '-an',
        '-movflags',
        '+faststart',
        '-y',
        str(output_path),
    ]


def _validate_output_file(output_path):
    if not output_path.exists():
        raise SocialVideoRenderError('FFmpeg nao gerou o arquivo MP4.')
    size = output_path.stat().st_size
    if size <= 0:
        raise SocialVideoRenderError('FFmpeg gerou um arquivo MP4 vazio.')
    max_bytes = settings.SOCIAL_REEL_MAX_FILE_MB * 1024 * 1024
    if size > max_bytes:
        raise SocialVideoRenderError('O Reel gerado ultrapassou o tamanho maximo configurado.')
    if output_path.suffix.lower() != '.mp4':
        raise SocialVideoRenderError('O arquivo gerado precisa ter extensao MP4.')
    return size


def _probe_output(output_path):
    ffprobe = ffprobe_path()
    if not ffprobe:
        return {}
    command = [
        ffprobe,
        '-v',
        'error',
        '-select_streams',
        'v:0',
        '-show_entries',
        'stream=codec_name,width,height,pix_fmt,duration',
        '-of',
        'default=noprint_wrappers=1',
        str(output_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
    except Exception:
        return {}
    data = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            data[key] = value
    return data


def renderizar_reel_social(content, *, return_diagnostics=False):
    total_start = time.monotonic()
    diagnostics = {'content_id': content.id}
    logger.info('reel_create_start content_id=%s', content.id)
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        logger.error('reel_render_error stage=ffmpeg_lookup exception_class=SocialVideoRenderError message=ffmpeg_missing')
        raise SocialVideoRenderError('FFmpeg nao esta disponivel no ambiente para gerar MP4.')

    duration = int(settings.SOCIAL_REEL_DURATION_SECONDS)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        frame_path = temp_dir / 'frame.jpg'
        output_path = temp_dir / 'reel.mp4'
        try:
            compose_start = time.monotonic()
            logger.info('reel_compose_start content_id=%s', content.id)
            frame = _compose_reel_frame(content)
            frame.save(frame_path, format='JPEG', quality=92, optimize=True)
            diagnostics['compose_ms'] = _elapsed_ms(compose_start)
            diagnostics['frame_path'] = 'frame.jpg'
            logger.info('reel_compose_end content_id=%s duration_ms=%s', content.id, diagnostics['compose_ms'])

            command = _ffmpeg_command(ffmpeg, frame_path, output_path, duration)
            diagnostics['ffmpeg_command'] = [item if item not in {str(frame_path), str(output_path)} else Path(item).name for item in command]
            ffmpeg_start = time.monotonic()
            logger.info('reel_ffmpeg_start content_id=%s', content.id)
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.SOCIAL_REEL_RENDER_TIMEOUT_SECONDS,
                check=True,
            )
            diagnostics['ffmpeg_ms'] = _elapsed_ms(ffmpeg_start)
            size = _validate_output_file(output_path)
            diagnostics['output_bytes'] = size
            diagnostics['probe'] = _probe_output(output_path)
            logger.info(
                'reel_ffmpeg_end content_id=%s duration_ms=%s returncode=%s output_bytes=%s',
                content.id,
                diagnostics['ffmpeg_ms'],
                result.returncode,
                size,
            )
        except subprocess.TimeoutExpired as exc:
            logger.error('reel_render_error stage=ffmpeg exception_class=TimeoutExpired message=timeout_%ss', settings.SOCIAL_REEL_RENDER_TIMEOUT_SECONDS)
            raise SocialVideoRenderError('Nao foi possivel gerar o Reel. Verifique os logs ou tente novamente.') from exc
        except subprocess.CalledProcessError as exc:
            logger.error('reel_render_error stage=ffmpeg exception_class=CalledProcessError message=%s', _sanitize_error(exc.stderr))
            raise SocialVideoRenderError('Nao foi possivel gerar o Reel. Verifique os logs ou tente novamente.') from exc
        except SocialRenderError as exc:
            logger.error('reel_render_error stage=validation exception_class=%s message=%s', type(exc).__name__, _sanitize_error(exc))
            raise
        video_bytes = output_path.read_bytes()

    filename = unique_media_filename('.mp4')
    storage_start = time.monotonic()
    logger.info('reel_storage_save_start content_id=%s', content.id)
    content.final_video.save(filename, ContentFile(video_bytes), save=True)
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='reel_rendered')
    diagnostics['storage_ms'] = _elapsed_ms(storage_start)
    diagnostics['total_ms'] = _elapsed_ms(total_start)
    logger.info('reel_storage_save_end content_id=%s duration_ms=%s', content.id, diagnostics['storage_ms'])
    logger.info('reel_create_end content_id=%s total_duration_ms=%s', content.id, diagnostics['total_ms'])
    if return_diagnostics:
        diagnostics['content'] = content
        return diagnostics
    return content


def auditar_video_reel(content):
    if not content.final_video:
        raise SocialVideoRenderError('Renderize o Reel antes de publicar.')
    with content.final_video.storage.open(content.final_video.name, 'rb') as arquivo:
        header = arquivo.read(12)
        arquivo.seek(0, 2)
        size = arquivo.tell()
    if b'ftyp' not in header:
        raise SocialVideoRenderError('O Reel final precisa ser MP4 valido.')
    max_bytes = settings.SOCIAL_REEL_MAX_FILE_MB * 1024 * 1024
    if size > max_bytes:
        raise SocialVideoRenderError('O Reel final ultrapassou o tamanho maximo configurado.')
    return {
        'name': content.final_video.name,
        'extension': Path(content.final_video.name).suffix.lower(),
        'format': 'MP4',
        'codec': REEL_CODEC,
        'width': REEL_SIZE[0],
        'height': REEL_SIZE[1],
        'fps': REEL_FPS,
        'duration': settings.SOCIAL_REEL_DURATION_SECONDS,
        'bytes': size,
    }
