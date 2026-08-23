from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont, ImageOps


class SocialRenderError(Exception):
    pass


CANVAS_SIZE = (1080, 1080)


def _font(size):
    candidates = [
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf'),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _line_height(draw, font):
    bbox = draw.textbbox((0, 0), 'Ag', font=font)
    return bbox[3] - bbox[1]


def _wrap(draw, text, font, max_width):
    lines = []
    for paragraph in (text or '').splitlines() or ['']:
        words = paragraph.split()
        if not words:
            lines.append('')
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f'{current} {word}'
            if _text_width(draw, candidate, font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _layout_text(draw, text, max_width, max_height):
    for size in range(78, 31, -2):
        font = _font(size)
        lines = _wrap(draw, text, font, max_width)
        line_height = _line_height(draw, font) + 12
        total_height = line_height * len(lines)
        if total_height <= max_height and all(_text_width(draw, line, font) <= max_width for line in lines):
            return font, lines, line_height, total_height
    raise SocialRenderError('Texto grande demais para renderizar com legibilidade.')


def renderizar_conteudo_social(content):
    if not content.base_image or not content.base_image.arquivo:
        raise SocialRenderError('Selecione uma imagem-base antes de renderizar.')

    try:
        with content.base_image.arquivo.open('rb') as arquivo:
            image = Image.open(arquivo)
            image = ImageOps.exif_transpose(image)
            image = ImageOps.fit(image, CANVAS_SIZE, method=Image.Resampling.LANCZOS)
            image = image.convert('RGB')
    except Exception as exc:
        raise SocialRenderError('Nao foi possivel abrir a imagem-base.') from exc

    overlay = Image.new('RGBA', CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin = 78
    max_width = CANVAS_SIZE[0] - margin * 2
    max_height = 420
    font, lines, line_height, text_height = _layout_text(draw, content.frase, max_width, max_height)

    padding_x = 46
    padding_y = 38
    band_height = text_height + padding_y * 2
    band_top = (CANVAS_SIZE[1] - band_height) // 2
    band_left = margin - 18
    band_right = CANVAS_SIZE[0] - margin + 18
    draw.rounded_rectangle(
        (band_left, band_top, band_right, band_top + band_height),
        radius=18,
        fill=(0, 0, 0, 150),
    )

    y = band_top + padding_y
    for line in lines:
        width = _text_width(draw, line, font)
        x = (CANVAS_SIZE[0] - width) // 2
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    final = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    buffer = BytesIO()
    final.save(buffer, format='JPEG', quality=90, optimize=True)
    filename = f'social/{content.profile_id}/posts/{uuid4().hex}.jpg'
    content.final_image.save(filename, ContentFile(buffer.getvalue()), save=True)
    return content
