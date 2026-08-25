from django.core.management.base import BaseCommand, CommandError

from social_automation.models import SocialContent
from social_automation.video_rendering import auditar_video_reel, ffmpeg_path, renderizar_reel_social


class Command(BaseCommand):
    help = 'Renderiza e diagnostica um Reel usando o mesmo renderer da UI, sem chamar Meta.'

    def add_arguments(self, parser):
        parser.add_argument('content_id', type=int)

    def handle(self, *args, **options):
        content = SocialContent.objects.select_related('profile', 'base_image').filter(pk=options['content_id']).first()
        if not content:
            raise CommandError('Conteudo nao encontrado.')
        if not content.is_reel:
            raise CommandError('Este conteudo nao esta marcado como Reel.')
        if not content.base_image:
            raise CommandError('Conteudo sem imagem-base.')

        self.stdout.write(f'Conteudo = {content.id}')
        self.stdout.write(f'Imagem = {content.base_image.nome}')
        self.stdout.write(f'FFmpeg = {ffmpeg_path() or "-"}')
        try:
            diagnostics = renderizar_reel_social(content, return_diagnostics=True)
            content.refresh_from_db()
            audit = auditar_video_reel(content)
        except Exception as exc:
            self.stdout.write(f'Resultado = ERRO')
            self.stdout.write(f'Erro = {type(exc).__name__}: {str(exc)[:240]}')
            raise

        self.stdout.write('Composicao = OK')
        self.stdout.write(f'Tempo composicao = {diagnostics.get("compose_ms")} ms')
        self.stdout.write(f'Tempo FFmpeg = {diagnostics.get("ffmpeg_ms")} ms')
        self.stdout.write(f'MP4 = {audit["name"]}')
        self.stdout.write(f'Bytes = {audit["bytes"]}')
        self.stdout.write(f'Codec = {diagnostics.get("probe", {}).get("codec_name") or audit["codec"]}')
        self.stdout.write(f'Resolucao = {diagnostics.get("probe", {}).get("width") or audit["width"]}x{diagnostics.get("probe", {}).get("height") or audit["height"]}')
        self.stdout.write(f'Duracao = {diagnostics.get("probe", {}).get("duration") or audit["duration"]}')
        self.stdout.write('Storage salvo = SIM')
        self.stdout.write(f'Tempo total = {diagnostics.get("total_ms")} ms')
        self.stdout.write('Resultado = OK')
