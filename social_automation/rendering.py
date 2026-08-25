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
TEXT_BOX_PADDING = 24


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
    if position in {'auto', 'auto_smart'}:
        position = AUTO_POSITION
    if position == 'left':
        return (SAFE_MARGIN, 112, 540, 856), 'left'
    if position == 'right':
        return (462, 112, 540, 856), 'right'
    if position == 'top':
        return (SAFE_MARGIN, SAFE_MARGIN, 924, 380), 'center'
    return (SAFE_MARGIN, 626, 924, 354), 'center'


def _percent_region(x, y, width, height):
    return (
        max(0, min(CANVAS_SIZE[0], round(CANVAS_SIZE[0] * float(x) / 100))),
        max(0, min(CANVAS_SIZE[1], round(CANVAS_SIZE[1] * float(y) / 100))),
        max(1, min(CANVAS_SIZE[0], round(CANVAS_SIZE[0] * float(width) / 100))),
        max(1, min(CANVAS_SIZE[1], round(CANVAS_SIZE[1] * float(height) / 100))),
    )


def _normalize_align(value, default='center'):
    return value if value in {'left', 'center', 'right', 'top', 'middle', 'bottom'} else default


def _region_gradient_position(region):
    x, y, width, height = region
    center_x = x + width / 2
    center_y = y + height / 2
    if center_y < CANVAS_SIZE[1] * 0.35:
        return 'top'
    if center_y > CANVAS_SIZE[1] * 0.65:
        return 'bottom'
    if center_x < CANVAS_SIZE[0] * 0.5:
        return 'left'
    return 'right'


def _configured_text_boxes(base_image):
    boxes = []
    if getattr(base_image, 'primary_text_box_configured', False):
        region = _percent_region(
            base_image.primary_text_box_x,
            base_image.primary_text_box_y,
            base_image.primary_text_box_width,
            base_image.primary_text_box_height,
        )
        boxes.append(
            {
                'name': 'primary',
                'region': region,
                'align_horizontal': _normalize_align(base_image.text_align_horizontal, 'center'),
                'align_vertical': _normalize_align(base_image.text_align_vertical, 'middle'),
                'gradient_position': _region_gradient_position(region),
            }
        )
    if getattr(base_image, 'secondary_text_box_configured', False):
        region = _percent_region(
            base_image.secondary_text_box_x,
            base_image.secondary_text_box_y,
            base_image.secondary_text_box_width,
            base_image.secondary_text_box_height,
        )
        boxes.append(
            {
                'name': 'secondary',
                'region': region,
                'align_horizontal': _normalize_align(base_image.secondary_text_align_horizontal, 'center'),
                'align_vertical': _normalize_align(base_image.secondary_text_align_vertical, 'middle'),
                'gradient_position': _region_gradient_position(region),
            }
        )
    return boxes


def _legacy_text_boxes(base_image):
    position = getattr(base_image, 'text_position', AUTO_POSITION) or AUTO_POSITION
    region, align = _region(position)
    gradient_position = AUTO_POSITION if position in {'auto', 'auto_smart'} else position
    return [
        {
            'name': 'legacy',
            'region': region,
            'align_horizontal': align,
            'align_vertical': 'middle',
            'gradient_position': gradient_position,
        }
    ]


def _text_boxes(base_image):
    configured = _configured_text_boxes(base_image)
    return configured or _legacy_text_boxes(base_image)


def _inner_region(region):
    x, y, width, height = region
    padding = min(TEXT_BOX_PADDING, max(width // 10, 0), max(height // 10, 0))
    return (x + padding, y + padding, max(1, width - padding * 2), max(1, height - padding * 2))


def _apply_gradient(overlay, position, region):
    width, height = overlay.size
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


def _draw_text_box(overlay, text, box):
    region = box['region']
    inner = _inner_region(region)
    draw = ImageDraw.Draw(overlay)
    font, lines, line_height, text_height = _layout_text(draw, text, inner[2], inner[3])

    if box['align_vertical'] == 'top':
        y = inner[1]
    elif box['align_vertical'] == 'bottom':
        y = inner[1] + max(inner[3] - text_height, 0)
    else:
        y = inner[1] + max((inner[3] - text_height) // 2, 0)

    canvas_size = overlay.size
    text_layer = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    for line in lines:
        width = _text_width(text_draw, line, font)
        if box['align_horizontal'] == 'left':
            x = inner[0]
        elif box['align_horizontal'] == 'right':
            x = inner[0] + inner[2] - width
        else:
            x = inner[0] + (inner[2] - width) // 2
        text_draw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 150))
        text_draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 170))
        y += line_height

    mask = Image.new('L', canvas_size, 0)
    ImageDraw.Draw(mask).rectangle((region[0], region[1], region[0] + region[2], region[1] + region[3]), fill=255)
    clipped = Image.composite(text_layer, Image.new('RGBA', canvas_size, (0, 0, 0, 0)), mask)
    overlay.alpha_composite(clipped)
    return {
        'box': box['name'],
        'font_size': getattr(font, 'size', None),
        'lines': len(lines),
    }


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
    boxes = _text_boxes(content.base_image)
    last_error = None
    for box in boxes:
        candidate_overlay = Image.new('RGBA', CANVAS_SIZE, (0, 0, 0, 0))
        _apply_gradient(candidate_overlay, box['gradient_position'], box['region'])
        try:
            _draw_text_box(candidate_overlay, content.frase, box)
        except SocialRenderError as exc:
            last_error = exc
            continue
        overlay = candidate_overlay
        break
    else:
        raise last_error or SocialRenderError('Texto grande demais para renderizar com legibilidade.')

    final = Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')
    buffer = BytesIO()
    final.save(buffer, format='JPEG', quality=90, optimize=True)
    filename = f'social/{content.profile_id}/posts/{uuid4().hex}.jpg'
    content.final_image.save(filename, ContentFile(buffer.getvalue()), save=True)
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='image_rendered')
    return content


def renderizar_midia_social(content):
    if getattr(content, 'is_reel', False):
        from .video_rendering import renderizar_reel_social

        return renderizar_reel_social(content)
    return renderizar_conteudo_social(content)
