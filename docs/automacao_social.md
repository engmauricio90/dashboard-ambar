# Automacao Social

## Variaveis de ambiente

```env
OPENAI_API_KEY=
OPENAI_SOCIAL_MODEL=gpt-5.6-luna
OPENAI_SOCIAL_TIMEOUT_SECONDS=60
OPENAI_SOCIAL_MAX_BATCH=30
OPENAI_SOCIAL_MODERATION_MODEL=omni-moderation-latest
```

Sem `OPENAI_API_KEY`, a tela de geracao com IA permanece acessivel, mas o sistema informa que a chave precisa ser configurada.

## Fluxo operacional

1. Cadastre um perfil social.
2. Cadastre imagens-base ativas com tags.
3. Acesse o perfil e clique em `Gerar com IA`.
4. Informe quantidade e tema opcional.
5. O sistema gera rascunhos, modera o texto, escolhe imagem-base ativa e renderiza o card final.
6. Revise a fila antes de aprovar ou agendar.

Nesta fase nao ha publicacao automatica, API do Instagram, cron, Celery ou agendamento real externo.

## Instagram API

Variaveis exigidas em producao para publicacao manual:

```env
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_USER_ID=
INSTAGRAM_API_VERSION=v23.0
INSTAGRAM_EXPECTED_USERNAME=lailapistola
INSTAGRAM_MEDIA_URL_TTL_SECONDS=3600
INSTAGRAM_API_TIMEOUT_SECONDS=30
PLATFORM_BASE_URL=https://dashboard-ambar.onrender.com
```

O token nunca deve ser salvo no banco, exibido em tela ou registrado em log.

Fluxo manual:

1. Aprovar um `SocialContent`.
2. Garantir que ele tenha `final_image`.
3. Clicar em `Publicar no Instagram`.
4. O sistema gera uma URL publica temporaria assinada para a imagem final.
5. A API oficial do Instagram cria o container de midia.
6. O sistema publica o container e salva `external_post_id`, `external_permalink` e `published_at`.

Smoke read-only:

```bash
python manage.py testar_instagram
```

Esse comando valida configuracao e conta conectada sem publicar nada.
