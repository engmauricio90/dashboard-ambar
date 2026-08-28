from django.core.management.base import BaseCommand, CommandError

from social_automation.instagram import InstagramAPIError, criar_container_imagem, get_instagram_credentials, montar_caption, resumir_image_url, url_midia_temporaria
from social_automation.models import SocialContent


class Command(BaseCommand):
    help = 'Diagnostica criacao de container Instagram sem executar media_publish.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)
        parser.add_argument('--external-url', default='')
        parser.add_argument('--jpg-url', action='store_true')

    def handle(self, *args, **options):
        content = SocialContent.objects.select_related('profile').filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        credentials = get_instagram_credentials(content.profile)

        old_url = url_midia_temporaria(content, com_extensao_jpg=options['jpg_url'], legacy=True)
        meta_compat_url = url_midia_temporaria(content)
        self._testar('ROTA_ANTIGA', old_url, '', credentials)
        self._testar('META_COMPAT_SEM_CAPTION', meta_compat_url, '', credentials)
        self._testar('META_COMPAT_COM_CAPTION', meta_compat_url, montar_caption(content), credentials)

        external_url = options.get('external_url') or ''
        if external_url:
            self._testar('URL_EXTERNA_SEM_CAPTION', external_url, '', credentials)
            self._testar('URL_EXTERNA_COM_CAPTION', external_url, montar_caption(content), credentials)
        else:
            self.stdout.write('URL_EXTERNA: nao executada')

        self.stdout.write('media_publish: NAO executado')

    def _testar(self, label, image_url, caption, credentials):
        resumo = resumir_image_url(image_url)
        self.stdout.write(f'{label}: iniciando')
        self.stdout.write(f'{label}: image_url_scheme={resumo["scheme"]}')
        self.stdout.write(f'{label}: image_url_host={resumo["host"]}')
        self.stdout.write(f'{label}: image_url_path_structure={resumo["path_structure"]}')
        self.stdout.write(f'{label}: image_url_length={resumo["length"]}')
        self.stdout.write(f'{label}: image_url_sha256={resumo["sha256"]}')
        try:
            container_id = criar_container_imagem(image_url, caption, credentials=credentials)
            self.stdout.write(f'{label}: OK container_id={self._mask(container_id)}')
        except InstagramAPIError as exc:
            self.stdout.write(f'{label}: ERRO')
            self.stdout.write(f'message={exc}')
            self.stdout.write(f'type={exc.error_type or "-"}')
            self.stdout.write(f'code={exc.code or "-"}')
            self.stdout.write(f'subcode={exc.subcode or "-"}')
            self.stdout.write(f'is_transient={exc.is_transient}')
            self.stdout.write(f'error_user_title={exc.user_title or "-"}')
            self.stdout.write(f'error_user_msg={exc.user_msg or "-"}')
            self.stdout.write(f'fbtrace_id={exc.fbtrace_id or "-"}')

    def _mask(self, value):
        value = str(value or '')
        if len(value) <= 8:
            return '***'
        return f'{value[:4]}...{value[-4:]}'
