from pathlib import Path

from PIL import Image, ImageDraw


def _clean(value):
    return str(value or '').strip()


def hex_to_rgb(value, fallback=(31, 41, 55)):
    value = _clean(value)
    if value.startswith('#') and len(value) == 7:
        try:
            return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
        except ValueError:
            return fallback
    return fallback


def _image_from_field(field):
    if not field:
        return None
    try:
        path = Path(field.path)
    except (NotImplementedError, ValueError):
        return None
    if not path.exists():
        return None
    try:
        return Image.open(path).convert('RGBA')
    except OSError:
        return None


def paste_image_fit(base, image, box):
    if not image:
        return
    x, y, w, h = box
    image = image.copy()
    image.thumbnail((w, h))
    base.paste(image, (x + (w - image.width) // 2, y + (h - image.height) // 2), image)


def draw_empresa_header(image, draw, empresa, font, bold_font, margin=64, height=112):
    if not empresa:
        return margin + height

    cabecalho = _image_from_field(empresa.cabecalho_documentos)
    if cabecalho:
        paste_image_fit(image, cabecalho, (margin, 20, image.width - margin * 2, height))
        return 20 + height + 24

    primary = hex_to_rgb(empresa.cor_primaria, (31, 41, 55))
    draw.rounded_rectangle([margin, 24, image.width - margin, 24 + height], radius=8, outline=(203, 213, 225), width=2, fill=(248, 250, 252))
    logo = _image_from_field(empresa.logo)
    if logo:
        paste_image_fit(image, logo, (margin + 22, 38, 130, height - 28))
        text_x = margin + 170
    else:
        text_x = margin + 28

    nome = empresa.nome_documento
    draw.text((text_x, 48), nome, font=bold_font, fill=primary)
    y = 82
    for line in empresa.linhas_institucionais[:2]:
        draw.text((text_x, y), line, font=font, fill=(71, 85, 105))
        y += 24
    return 24 + height + 24


def draw_empresa_footer(image, draw, empresa, font, bold_font=None, margin=64, y=None, page_text=''):
    y = y if y is not None else image.height - 72
    if not empresa:
        if page_text:
            draw.text((image.width - margin - font.getlength(page_text), y), page_text, font=font, fill=(100, 116, 139))
        return

    rodape = _image_from_field(empresa.rodape_documentos)
    if rodape:
        paste_image_fit(image, rodape, (margin, y - 12, image.width - margin * 2, 54))
    else:
        text = empresa.texto_rodape or ' | '.join(empresa.linhas_institucionais)
        if not text:
            text = empresa.nome
        if page_text:
            draw.text(((image.width - font.getlength(text)) / 2, y), text, font=font, fill=(100, 116, 139))
        else:
            draw.text((margin, y), text, font=font, fill=(100, 116, 139))

    if page_text:
        draw.text((image.width - margin - font.getlength(page_text), y), page_text, font=font, fill=(100, 116, 139))
