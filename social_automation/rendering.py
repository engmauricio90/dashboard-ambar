from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont, ImageOps


class SocialRenderError(Exception):
    pass


CANVAS_SIZE = (1080, 1080)
SAFE_MARGIN = 78
AUTO_POSITION = 'bottom'
MAX_FONT_SIZE = 72
MIN_FONT_SIZE = 28
IDEAL_MAX_LINES = 4
ACCEPTABLE_MAX_LINES = 5


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


def _layout_candidate(draw, text, max_width, max_height, size):
    font = _font(size)
    lines = _wrap(draw, text, font, max_width)
    line_height = _line_height(draw, font) + max(8, size // 7)
    total_height = line_height * len(lines)
    fits = total_height <= max_height and all(_text_width(draw, line, font) <= max_width for line in lines)
    return {
        'font': font,
        'lines': lines,
        'line_height': line_height,
        'total_height': total_height,
        'fits': fits,
        'size': size,
    }


def _candidate_score(candidate):
    line_count = len(candidate['lines'])
    if 2 <= line_count <= IDEAL_MAX_LINES:
        line_penalty = 0
    elif line_count == 1:
        line_penalty = 8
    elif line_count <= ACCEPTABLE_MAX_LINES:
        line_penalty = 18
    else:
        line_penalty = 60 + (line_count - ACCEPTABLE_MAX_LINES) * 20
    return (line_penalty, -candidate['size'])


def _layout_text(draw, text, max_width, max_height):
    candidates = []
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        candidate = _layout_candidate(draw, text, max_width, max_height, size)
        if candidate['fits']:
            candidates.append(candidate)
    if candidates:
        best = sorted(candidates, key=_candidate_score)[0]
        return best['font'], best['lines'], best['line_height'], best['total_height']
    for size in range(MIN_FONT_SIZE - 2, 19, -2):
        font = _font(size)
        lines = _wrap(draw, text, font, max_width)
        line_height = _line_height(draw, font) + 8
        total_height = line_height * len(lines)
        if total_height <= max_height and all(_text_width(draw, line, font) <= max_width for line in lines):
            return font, lines, line_height, total_height
    raise SocialRenderError('Texto grande demais para renderizar com legibilidade.')


def _region(position):
    position = position or AUTO_POSITION
    if position == 'auto':
        position = AUTO_POSITION
    if position == 'left':
        return (SAFE_MARGIN, 112, 540, 856), 'left'
    if position == 'right':
        return (462, 112, 540, 856), 'right'
    if position == 'top':
        return (SAFE_MARGIN, SAFE_MARGIN, 924, 380), 'center'
    return (SAFE_MARGIN, 626, 924, 354), 'center'


def _apply_gradient(overlay, position, region):
    width, height = CANVAS_SIZE
    pixels = ImageDraw.Draw(overlay)
    max_alpha = 120
    if position in {'auto', 'bottom'}:
        start = max(region[1] - 70, 0)
        for y in range(start, height):
            progress = (y - start) / max(height - start, 1)
            alpha = int(max_alpha * progress)
            pixels.line((0, y, width, y), fill=(0, 0, 0, alpha))
    elif position == 'top':
        end = min(region[1] + region[3] + 90, height)
        for y in range(0, end):
            progress = 1 - (y / max(end, 1))
            alpha = int(max_alpha * progress)
            pixels.line((0, y, width, y), fill=(0, 0, 0, alpha))
    elif position == 'left':
        end = min(region[0] + region[2] + 120, width)
        for x in range(0, end):
            progress = 1 - (x / max(end, 1))
            alpha = int(max_alpha * progress)
            pixels.line((x, 0, x, height), fill=(0, 0, 0, alpha))
    elif position == 'right':
        start = max(region[0] - 120, 0)
        for x in range(start, width):
            progress = (x - start) / max(width - start, 1)
            alpha = int(max_alpha * progress)
            pixels.line((x, 0, x, height), fill=(0, 0, 0, alpha))


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
    position = getattr(content.base_image, 'text_position', AUTO_POSITION) or AUTO_POSITION
    region, align = _region(position)
    _apply_gradient(overlay, position, region)
    max_width = region[2]
    max_height = region[3]
    font, lines, line_height, text_height = _layout_text(draw, content.frase, max_width, max_height)

    y = region[1] + max((region[3] - text_height) // 2, 0)
    for line in lines:
        width = _text_width(draw, line, font)
        if align == 'left':
            x = region[0]
        elif align == 'right':
            x = region[0] + region[2] - width
        else:
            x = region[0] + (region[2] - width) // 2
        draw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 150))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 170))
        y += line_height

    final = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    buffer = BytesIO()
    final.save(buffer, format='JPEG', quality=90, optimize=True)
    filename = f'social/{content.profile_id}/posts/{uuid4().hex}.jpg'
    content.final_image.save(filename, ContentFile(buffer.getvalue()), save=True)
    return content
