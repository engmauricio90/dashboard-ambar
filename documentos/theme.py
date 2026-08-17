from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from empresas.documentos import hex_to_rgb


@dataclass(frozen=True)
class PageGeometry:
    width: int
    height: int
    margin_left: int
    margin_right: int
    margin_top: int
    margin_bottom: int
    header_height: int
    footer_height: int

    @property
    def content_left(self):
        return self.margin_left

    @property
    def content_right(self):
        return self.width - self.margin_right

    @property
    def content_width(self):
        return self.content_right - self.content_left

    @property
    def content_top(self):
        return self.margin_top + self.header_height

    @property
    def content_bottom(self):
        return self.height - self.margin_bottom - self.footer_height


class DocumentTheme:
    A4_PORTRAIT = (1654, 2339)
    A4_LANDSCAPE = (2339, 1654)

    def __init__(self, empresa=None, orientation='portrait'):
        self.empresa = empresa
        self.orientation = orientation
        self.primary = hex_to_rgb(getattr(empresa, 'cor_primaria', ''), (15, 76, 92))
        self.secondary = hex_to_rgb(getattr(empresa, 'cor_secundaria', ''), (71, 85, 105))
        self.text = (17, 24, 39)
        self.muted = (75, 85, 99)
        self.border = (203, 213, 225)
        self.light_border = (226, 232, 240)
        self.surface = (248, 250, 252)
        self.zebra = (250, 251, 253)
        self.header_fill = (232, 238, 243)
        self.positive = (22, 101, 52)
        self.negative = (185, 28, 28)
        self.warning = (146, 64, 14)
        page_w, page_h = self.A4_LANDSCAPE if orientation == 'landscape' else self.A4_PORTRAIT
        self.geometry = PageGeometry(
            width=page_w,
            height=page_h,
            margin_left=70,
            margin_right=70,
            margin_top=54,
            margin_bottom=54,
            header_height=126,
            footer_height=64,
        )

    @property
    def company_name(self):
        return getattr(self.empresa, 'nome_documento', None) or getattr(self.empresa, 'nome', '') or 'Empresa'

    @property
    def company_document(self):
        return getattr(self.empresa, 'cnpj', '') or ''

    @property
    def company_lines(self):
        return list(getattr(self.empresa, 'linhas_institucionais', []) or [])

    def font(self, level='body', bold=False):
        sizes = {
            'document_title': 31,
            'section_title': 20,
            'subsection_title': 18,
            'body': 17,
            'table_header': 16,
            'table_body': 15,
            'small': 14,
            'footer': 13,
            'total': 18,
        }
        size = sizes.get(level, sizes['body'])
        candidates = [
            Path('C:/Windows/Fonts') / ('arialbd.ttf' if bold else 'arial.ttf'),
            Path('C:/Windows/Fonts') / ('calibrib.ttf' if bold else 'calibri.ttf'),
            Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
            Path('/usr/share/fonts/truetype/liberation2') / ('LiberationSans-Bold.ttf' if bold else 'LiberationSans-Regular.ttf'),
        ]
        for candidate in candidates:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
        return ImageFont.load_default()
