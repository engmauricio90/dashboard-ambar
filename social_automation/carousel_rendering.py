from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageOps

from .models import SocialCarouselSlide, SocialCarouselTemplate
from .rendering import SocialRenderError, _font, _layout_text, _text_width


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


def _draw_aligned_lines(draw, lines, font, *, x, y, width, line_height, fill, align):
    for line in lines:
        line_width = _text_width(draw, line, font)
        if align == SocialCarouselTemplate.TextAlignment.RIGHT:
            line_x = x + width - line_width
        elif align == SocialCarouselTemplate.TextAlignment.CENTER:
            line_x = x + (width - line_width) // 2
        else:
            line_x = x
        draw.text((line_x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _draw_label(draw, template, text, y, *, bold=False):
    if not text:
        return y
    width, height = template.canvas_size
    margin = 76
    font_size = 34 if bold else 28
    font = _font(font_size)
    fill = _hex_to_rgb(template.text_color, (255, 255, 255))
    draw.text((margin, y), text, font=font, fill=fill)
    return y + font_size + 16


def _draw_slide(canvas, slide, template, total_slides):
    draw = ImageDraw.Draw(canvas)
    width, height = template.canvas_size
    margin = 76
    text_color = _hex_to_rgb(template.text_color, (255, 255, 255))
    accent_color = _hex_to_rgb(template.accent_color, (34, 197, 94))

    if slide.source_image:
        with slide.source_image.open('rb') as arquivo:
            source = Image.open(arquivo)
            source = ImageOps.exif_transpose(source)
            source = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS).convert('RGB')
        canvas.paste(Image.blend(source, canvas, 0.35))

    y = margin
    if template.show_profile_name:
        y = _draw_label(draw, template, slide.content.profile.nome, y)

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
        title_font, title_lines, title_line_height, title_total_height = _layout_text(draw, title, max_width, title_height)
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
        )
        y += 28

    if body:
        body_font, body_lines, body_line_height, body_total_height = _layout_text(draw, body, max_width, body_height)
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
        )

    if template.show_slide_number:
        marker = f'{slide.order}/{total_slides}'
        font = _font(28)
        marker_width = _text_width(draw, marker, font)
        draw.text((width - margin - marker_width, height - margin), marker, font=font, fill=text_color)
    if template.show_footer:
        footer = template.footer_text or slide.content.profile.username
        font = _font(28)
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
        _draw_slide(canvas, slide, template, total_slides)
        buffer = BytesIO()
        canvas.save(buffer, format='JPEG', quality=92, optimize=True)
        filename = f'social/{content.profile_id}/carousels/{content.id}/slides/{uuid4().hex}.jpg'
        slide.rendered_image.save(filename, ContentFile(buffer.getvalue()), save=True)
        if slide.instagram_container_id or slide.instagram_container_fingerprint:
            slide.instagram_container_id = ''
            slide.instagram_container_fingerprint = ''
            slide.save(update_fields=['instagram_container_id', 'instagram_container_fingerprint', 'updated_at'])
    if content.status != content.Status.PUBLICADO:
        from .container_versioning import invalidate_instagram_container

        invalidate_instagram_container(content, reason='carousel_rendered')
    return content
