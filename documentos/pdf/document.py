from dataclasses import dataclass
from io import BytesIO
import textwrap

from django.http import HttpResponse
from PIL import Image, ImageDraw

from documentos.formatting import format_date_br
from documentos.theme import DocumentTheme
from empresas.documentos import draw_empresa_footer, draw_empresa_header


@dataclass(frozen=True)
class PdfTableColumn:
    key: str
    label: str
    width: int | None = None
    weight: float = 1
    align: str = 'left'


def _clean_text(value):
    return str(value if value not in (None, '') else '-')


class PdfDocument:
    def __init__(self, empresa=None, title='', subtitle='', orientation='portrait', filename='documento.pdf'):
        self.theme = DocumentTheme(empresa, orientation=orientation)
        self.empresa = empresa
        self.title = title
        self.subtitle = subtitle
        self.filename = filename
        self.pages = []
        self.image = None
        self.draw = None
        self.y = 0
        self._new_page()

    @property
    def g(self):
        return self.theme.geometry

    def _new_page(self):
        if self.image is not None:
            self.pages.append(self.image)
        self.image = Image.new('RGB', (self.g.width, self.g.height), 'white')
        self.draw = ImageDraw.Draw(self.image)
        draw_empresa_header(
            self.image,
            self.draw,
            self.empresa,
            self.theme.font('small'),
            self.theme.font('section_title', True),
            margin=self.g.margin_left,
            height=84,
        )
        self.y = self.g.content_top

    def _ensure_space(self, needed):
        if self.y + needed <= self.g.content_bottom:
            return
        self._new_page()

    def _text_width(self, text, font):
        return self.draw.textlength(_clean_text(text), font=font)

    def _draw_wrapped(self, text, x, y, w, h, font, fill=None, align='left'):
        fill = fill or self.theme.text
        text = _clean_text(text)
        avg = max(font.getlength('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') / 52, 1)
        lines = textwrap.wrap(text, width=max(int((w - 12) / avg), 4)) or ['']
        line_h = font.getbbox('Ag')[3] - font.getbbox('Ag')[1] + 4
        visible = lines[: max(int((h - 8) / line_h), 1)]
        if len(lines) > len(visible) and visible:
            visible[-1] = f'{visible[-1][: max(len(visible[-1]) - 3, 1)]}...'
        y_text = y + max((h - (line_h * len(visible))) // 2, 4)
        for line in visible:
            if align == 'right':
                x_text = x + w - self._text_width(line, font) - 7
            elif align == 'center':
                x_text = x + (w - self._text_width(line, font)) / 2
            else:
                x_text = x + 7
            self.draw.text((x_text, y_text), line, font=font, fill=fill)
            y_text += line_h

    def add_title(self, title=None, subtitle=None, filters=None, emitted_on=None):
        title = title or self.title
        subtitle = subtitle or self.subtitle
        title_font = self.theme.font('document_title', True)
        body_font = self.theme.font('body')
        small_font = self.theme.font('small')
        needed = 86 + (30 if subtitle else 0) + (30 if filters else 0)
        self._ensure_space(needed)
        x = self.g.content_left
        self.draw.text((x, self.y), _clean_text(title), font=title_font, fill=self.theme.text)
        if emitted_on:
            emitted = f'Emitido em {format_date_br(emitted_on)}'
            self.draw.text((self.g.content_right - self._text_width(emitted, small_font), self.y + 10), emitted, font=small_font, fill=self.theme.muted)
        self.y += 44
        if subtitle:
            self.draw.text((x, self.y), _clean_text(subtitle), font=body_font, fill=self.theme.muted)
            self.y += 30
        if filters:
            self.draw.text((x, self.y), _clean_text(filters), font=small_font, fill=self.theme.muted)
            self.y += 30
        self.draw.line((x, self.y + 4, self.g.content_right, self.y + 4), fill=self.theme.light_border, width=2)
        self.y += 28

    def add_info_grid(self, items, columns=4):
        if not items:
            return
        row_h = 62
        rows = (len(items) + columns - 1) // columns
        self._ensure_space(rows * row_h + 20)
        col_w = self.g.content_width / columns
        label_font = self.theme.font('small', True)
        value_font = self.theme.font('body')
        for index, (label, value) in enumerate(items):
            col = index % columns
            row = index // columns
            x = int(self.g.content_left + col * col_w)
            y = self.y + row * row_h
            self.draw.rectangle((x, y, x + int(col_w), y + row_h), fill=self.theme.surface, outline=self.theme.border, width=1)
            self.draw.text((x + 9, y + 8), _clean_text(label).upper(), font=label_font, fill=self.theme.muted)
            self._draw_wrapped(value, x + 3, y + 28, int(col_w - 6), 28, value_font)
        self.y += rows * row_h + 24

    def add_totals_box(self, rows, width=720):
        if not rows:
            return
        row_h = 42
        h = row_h * len(rows) + 18
        self._ensure_space(h + 18)
        x = self.g.content_right - width
        self.draw.rounded_rectangle((x, self.y, x + width, self.y + h), radius=8, fill=self.theme.surface, outline=self.theme.border, width=2)
        y = self.y + 10
        for label, value, is_total in rows:
            font = self.theme.font('total' if is_total else 'body', is_total)
            self.draw.text((x + 18, y + 9), _clean_text(label), font=font, fill=self.theme.text)
            value_text = _clean_text(value)
            self.draw.text((x + width - 18 - self._text_width(value_text, font), y + 9), value_text, font=font, fill=self.theme.text)
            y += row_h
            if is_total:
                self.draw.line((x + 16, y - row_h + 4, x + width - 16, y - row_h + 4), fill=self.theme.border, width=1)
        self.y += h + 24

    def add_table(self, columns, rows, row_height=42):
        if not rows:
            rows = []
        table_w = self.g.content_width
        fixed = sum(col.width or 0 for col in columns)
        flexible = [col for col in columns if col.width is None]
        remaining = max(table_w - fixed, 0)
        total_weight = sum(col.weight for col in flexible) or 1
        widths = []
        for col in columns:
            widths.append(col.width if col.width is not None else int(remaining * col.weight / total_weight))
        widths[-1] += table_w - sum(widths)

        def draw_header():
            self._ensure_space(row_height * 2)
            x = self.g.content_left
            for col, width in zip(columns, widths):
                self.draw.rectangle((x, self.y, x + width, self.y + row_height), fill=self.theme.primary, outline=self.theme.primary, width=1)
                self._draw_wrapped(col.label, x, self.y, width, row_height, self.theme.font('table_header', True), fill='white', align='center')
                x += width
            self.y += row_height

        draw_header()
        for row_index, row in enumerate(rows):
            self._ensure_space(row_height)
            if self.y == self.g.content_top:
                draw_header()
            x = self.g.content_left
            bg = self.theme.zebra if row_index % 2 else (255, 255, 255)
            for col, width in zip(columns, widths):
                self.draw.rectangle((x, self.y, x + width, self.y + row_height), fill=bg, outline=self.theme.border, width=1)
                self._draw_wrapped(row.get(col.key, '-'), x, self.y, width, row_height, self.theme.font('table_body'), align=col.align)
                x += width
            self.y += row_height
        self.y += 22

    def build(self):
        if self.image is not None:
            self.pages.append(self.image)
            self.image = None
        total = len(self.pages)
        for index, page in enumerate(self.pages, start=1):
            draw = ImageDraw.Draw(page)
            page_text = f'Pagina {index} de {total}'
            draw_empresa_footer(page, draw, self.empresa, self.theme.font('footer'), self.theme.font('footer', True), margin=self.g.margin_left, y=self.g.height - self.g.margin_bottom, page_text=page_text)
        buffer = BytesIO()
        self.pages[0].save(buffer, 'PDF', save_all=True, append_images=self.pages[1:], resolution=150)
        return buffer.getvalue()

    def response(self):
        response = HttpResponse(self.build(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{self.filename}"'
        return response
