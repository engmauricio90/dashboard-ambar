from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageOps

from .media_paths import unique_media_filename
from .models import SocialCarouselSlide, SocialCarouselTemplate
from .rendering import SocialRenderError, _font, _layout_text, _text_width
from .typography import typography_for_identity
from .visual_composer import VisualCompositionError, compose_carousel_slide


SLIDE_MIN = 2
SLIDE_MAX = 10


def _hex_to_rgb(value, default):
    value = (value or '').strip().lstrip('#')
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return default


def _background(template):
    size = template.canvas_size
    if template.background_type == SocialCarouselTemplate.BackgroundType.IMAGE and template.background_image:
        with template.background_image.open('rb') as arquivo:
            image = Image.open(arquivo)
            image = ImageOps.exif_transpose(image)
            return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS).convert('RGB')
    color_a = _hex_to_rgb(template.background_color, (17, 24, 39))
    color_b = _hex_to_rgb(template.secondary_background_color, (51, 65, 85))
    if template.background_type == SocialCarouselTemplate.BackgroundType.SOLID:
        return Image.new('RGB', size, color_a)
    image = Image.new('RGB', size, color_a)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        progress = y / max(size[1] - 1, 1)
        color = tuple(round(color_a[i] * (1 - progress) + color_b[i] * progress) for i in range(3))
        draw.line((0, y, size[0], y), fill=color)
    return image


def _draw_aligned_lines(draw, lines, font, *, x, y, width, line_height, fill, align, typography=None):
    for line in lines:
        line_width = _text_width(draw, line, font)
        if align == SocialCarouselTemplate.TextAlignment.RIGHT:
            line_x = x + width - line_width
        elif align == SocialCarouselTemplate.TextAlignment.CENTER:
            line_x = x + (width - line_width) // 2
        else:
            line_x = x
        shadow_offset = getattr(typography, 'shadow_offset', (0, 0))
        shadow_alpha = getattr(typography, 'shadow_alpha', 0)
        outline_width = getattr(typography, 'outline_width', 0)
        outline_alpha = getattr(typography, 'outline_alpha', 0)
        if shadow_alpha and shadow_offset != (0, 0):
            draw.text((line_x + shadow_offset[0], y + shadow_offset[1]), line, font=font, fill=(0, 0, 0, shadow_alpha))
        draw.text(
            (line_x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=outline_width,
            stroke_fill=(0, 0, 0, outline_alpha),
        )
        y += line_height
    return y


def _draw_label(draw, template, text, y, *, bold=False, typography=None):
    if not text:
        return y
    width, height = template.canvas_size
    margin = 76
    font_size = 34 if bold else 28
    font = _font(font_size, typography)
    fill = _hex_to_rgb(template.text_color, (255, 255, 255))
    draw.text((margin, y), text, font=font, fill=fill)
    return y + font_size + 16


def _apply_composed_overlay(canvas, decision):
    overlay_type = decision.overlay_type
    strength = max(0, min(230, round(255 * decision.overlay_strength / 100)))
    if not strength or overlay_type == 'NONE':
        return
    width, height = canvas.size
    overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if overlay_type == 'LIGHT':
        draw.rectangle((0, 0, width, height), fill=(255, 255, 255, strength))
    elif overlay_type == 'DARK':
        draw.rectangle((0, 0, width, height), fill=(0, 0, 0, strength))
    elif overlay_type in {'GRADIENT_LEFT', 'GRADIENT_RIGHT'}:
        for x in range(width):
            progress = 1 - (x / max(width - 1, 1)) if overlay_type == 'GRADIENT_LEFT' else x / max(width - 1, 1)
            draw.line((x, 0, x, height), fill=(0, 0, 0, round(strength * progress)))
    elif overlay_type in {'GRADIENT_TOP', 'GRADIENT_BOTTOM'}:
        for y in range(height):
            progress = 1 - (y / max(height - 1, 1)) if overlay_type == 'GRADIENT_TOP' else y / max(height - 1, 1)
            draw.line((0, y, width, y), fill=(0, 0, 0, round(strength * progress)))
    canvas.alpha_composite(overlay)


def _draw_composed_text(draw, slide, decision, typography):
    x, y, width, height = decision.text_box
    padding = min(34, max(width // 16, 12), max(height // 12, 12))
    inner_x = x + padding
    inner_y = y + padding
    inner_width = max(1, width - padding * 2)
    inner_height = max(1, height - padding * 2)
    title = (slide.title or slide.content.frase or '').strip()
    body = (slide.body or '').strip()

    draw.rectangle((x, y, x + width, y + min(9, max(4, height // 40))), fill=decision.accent_color)
    cursor_y = inner_y + 18
    if title:
        title_height = inner_height if not body else max(120, round(inner_height * 0.42))
        title_font, title_lines, title_line_height, _ = _layout_text(draw, title, inner_width, title_height, typography)
        cursor_y = _draw_aligned_lines(
            draw,
            title_lines,
            title_font,
            x=inner_x,
            y=cursor_y,
            width=inner_width,
            line_height=title_line_height,
            fill=decision.text_color,
            align=decision.align,
            typography=typography,
        )
        cursor_y += 24
    if body:
        body_height = max(80, inner_y + inner_height - cursor_y)
        body_typography = typography
        body_font, body_lines, body_line_height, _ = _layout_text(draw, body, inner_width, body_height, body_typography)
        _draw_aligned_lines(
            draw,
            body_lines,
            body_font,
            x=inner_x,
            y=cursor_y,
            width=inner_width,
            line_height=body_line_height,
            fill=decision.text_color,
            align=decision.align,
            typography=body_typography,
        )


def _paste_source(canvas, slide, decision):
    source_file = None
    if slide.source_image:
        source_file = slide.source_image
    elif decision.use_source_photo and decision.source_base_image and decision.source_base_image.arquivo:
        source_file = decision.source_base_image.arquivo
    if not source_file:
        return
    with source_file.open('rb') as arquivo:
        source = Image.open(arquivo)
        source = ImageOps.exif_transpose(source)
        source = ImageOps.fit(source, canvas.size, method=Image.Resampling.LANCZOS).convert('RGB')
    canvas.paste(source)


def _draw_composed_slide(canvas, slide, template, total_slides):
    try:
        decision = compose_carousel_slide(slide, template, total_slides)
    except VisualCompositionError as exc:
        raise SocialRenderError(str(exc)) from exc
    identity = decision.source_base_image.profile.visual_identities.filter(active=True, is_default=True).first() if decision.source_base_image else slide.content.profile.visual_identities.filter(active=True, is_default=True).first()
    if identity is None:
        identity = slide.content.profile.visual_identities.filter(active=True).first()
    typography = typography_for_identity(identity, context='carousel') if identity else None
    _paste_source(canvas, slide, decision)
    canvas_rgba = canvas.convert('RGBA')
    _apply_composed_overlay(canvas_rgba, decision)
    draw = ImageDraw.Draw(canvas_rgba)
    width, height = template.canvas_size
    margin = 56
    if template.show_profile_name:
        label = decision.metadata.get('brand_name') or slide.content.profile.nome
        draw.text((margin, margin), label, font=_font(28, typography), fill=decision.text_color)
    _draw_composed_text(draw, slide, decision, typography)
    if template.show_slide_number:
        marker = f'{slide.order}/{total_slides}'
        font = _font(28, typography)
        marker_width = _text_width(draw, marker, font)
        draw.text((width - margin - marker_width, height - margin), marker, font=font, fill=decision.text_color)
    if template.show_footer:
        footer = template.footer_text or slide.content.profile.username
        draw.text((margin, height - margin), footer, font=_font(28, typography), fill=decision.text_color)
    slide.render_metadata = decision.metadata
    return canvas_rgba.convert('RGB')


def _draw_slide(canvas, slide, template, total_slides):
    draw = ImageDraw.Draw(canvas)
    width, height = template.canvas_size
    margin = 76
    text_color = _hex_to_rgb(template.text_color, (255, 255, 255))
    accent_color = _hex_to_rgb(template.accent_color, (34, 197, 94))
    identity = slide.content.profile.visual_identities.filter(active=True, is_default=True).first() or slide.content.profile.visual_identities.filter(active=True).first()
    typography = typography_for_identity(identity, context='carousel') if identity else None

    if slide.source_image:
        with slide.source_image.open('rb') as arquivo:
            source = Image.open(arquivo)
            source = ImageOps.exif_transpose(source)
            source = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS).convert('RGB')
        canvas.paste(Image.blend(source, canvas, 0.35))

    y = margin
    if template.show_profile_name:
        y = _draw_label(draw, template, slide.content.profile.nome, y, typography=typography)

    draw.rectangle((margin, y + 12, margin + 92, y + 22), fill=accent_color)
    y += 58

    title = (slide.title or slide.content.frase or '').strip()
    body = (slide.body or '').strip()
    max_width = width - margin * 2
    remaining_height = height - y - margin - 90
    if body:
        title_height = max(160, round(remaining_height * 0.32))
        body_height = max(260, remaining_height - title_height - 28)
    else:
        title_height = remaining_height
        body_height = 0

    if title:
        title_font, title_lines, title_line_height, title_total_height = _layout_text(draw, title, max_width, title_height, typography)
        y = _draw_aligned_lines(
            draw,
            title_lines,
            title_font,
            x=margin,
            y=y,
            width=max_width,
            line_height=title_line_height,
            fill=text_color,
            align=template.title_alignment,
            typography=typography,
        )
        y += 28

    if body:
        body_font, body_lines, body_line_height, body_total_height = _layout_text(draw, body, max_width, body_height, typography)
        _draw_aligned_lines(
            draw,
            body_lines,
            body_font,
            x=margin,
            y=y,
            width=max_width,
            line_height=body_line_height,
            fill=text_color,
            align=template.body_alignment,
            typography=typography,
        )

    if template.show_slide_number:
        marker = f'{slide.order}/{total_slides}'
        font = _font(28, typography)
        marker_width = _text_width(draw, marker, font)
        draw.text((width - margin - marker_width, height - margin), marker, font=font, fill=text_color)
    if template.show_footer:
        footer = template.footer_text or slide.content.profile.username
        font = _font(28, typography)
        draw.text((margin, height - margin), footer, font=font, fill=text_color)


def _template_for_content(content):
    if content.carousel_template:
        return content.carousel_template
    template = content.profile.carousel_templates.filter(active=True, is_default=True).first()
    if template:
        return template
    return SocialCarouselTemplate.objects.create(profile=content.profile, name='Template padrao', is_default=True)


def renderizar_carrossel_social(content):
    if not content.is_carousel:
        raise SocialRenderError('Conteudo nao e carrossel.')
    slides = list(content.carousel_slides.filter(is_active=True).order_by('order', 'id'))
    if len(slides) < SLIDE_MIN or len(slides) > SLIDE_MAX:
        raise SocialRenderError('Carrossel precisa ter entre 2 e 10 slides ativos.')
    template = _template_for_content(content)
    content.carousel_template = template
    content.save(update_fields=['carousel_template', 'updated_at'])
    total_slides = len(slides)
    for slide in slides:
        canvas = _background(template)
        canvas = _draw_composed_slide(canvas, slide, template, total_slides)
        buffer = BytesIO()
        canvas.save(buffer, format='JPEG', quality=92, optimize=True)
        filename = unique_media_filename('.jpg')
        slide.rendered_image.save(filename, ContentFile(buffer.getvalue()), save=True)
        if slide.instagram_container_id or slide.instagram_container_fingerprint:
            slide.instagram_container_id = ''
            slide.instagram_container_fingerprint = ''
            slide.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='carousel_rendered')
    return content
