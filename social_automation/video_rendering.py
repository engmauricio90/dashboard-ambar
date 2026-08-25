import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .rendering import SocialRenderError, _apply_gradient, _draw_text_box, _text_boxes


REEL_SIZE = (1080, 1920)
REEL_FPS = 30
REEL_CODEC = 'h264'


class SocialVideoRenderError(SocialRenderError):
    pass


def ffmpeg_path():
    return shutil.which('ffmpeg')


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

    scale_x = REEL_SIZE[0] / 1080
    scale_y = REEL_SIZE[1] / 1080
    boxes = []
    for box in _text_boxes(content.base_image):
        region = box['region']
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
    last_error = None
    for box in boxes:
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


def renderizar_reel_social(content):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise SocialVideoRenderError('FFmpeg nao esta disponivel no ambiente para gerar MP4.')

    frame = _compose_reel_frame(content)
    duration = int(settings.SOCIAL_REEL_DURATION_SECONDS)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        frame_path = temp_dir / 'frame.jpg'
        output_path = temp_dir / 'reel.mp4'
        frame.save(frame_path, format='JPEG', quality=92, optimize=True)
        command = [
            ffmpeg,
            '-y',
            '-loop',
            '1',
            '-i',
            str(frame_path),
            '-t',
            str(duration),
            '-r',
            str(REEL_FPS),
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            '-an',
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=duration + 30, check=False)
        if result.returncode != 0:
            raise SocialVideoRenderError('FFmpeg nao conseguiu gerar o Reel MP4.')
        video_bytes = output_path.read_bytes()

    max_bytes = settings.SOCIAL_REEL_MAX_FILE_MB * 1024 * 1024
    if len(video_bytes) > max_bytes:
        raise SocialVideoRenderError('O Reel gerado ultrapassou o tamanho maximo configurado.')

    filename = f'social/{content.profile_id}/reels/{uuid4().hex}.mp4'
    content.final_video.save(filename, ContentFile(video_bytes), save=True)
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
