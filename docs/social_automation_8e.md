# Automacao Social 8E

## Arquitetura

A automacao social roda pelo Web Service Django, nao pelo Render Cron diretamente. O Cron apenas faz uma chamada HTTPS para o endpoint interno:

`POST /internal/social-automation/tick/`

Isso preserva o acesso ao Persistent Disk do Web Service em `/var/data/media`, onde ficam as imagens renderizadas.

## Tick

O tick executa um ciclo limitado:

1. aplica lock de execucao;
2. processa perfis `AUTOMATICO`;
3. publica no maximo 1 post devido por perfil;
4. reagenda atrasados sem burst;
5. preenche agenda futura;
6. verifica estoque;
7. gera no maximo 1 lote quando estoque esta abaixo do alvo;
8. autoaprova somente conteudos gerados naquele ciclo;
9. retorna resumo JSON.

## Estoque

Defaults:

- minimo: `SOCIAL_AUTOMATION_QUEUE_MIN=40`
- alvo: `SOCIAL_AUTOMATION_QUEUE_TARGET=60`
- batch: `SOCIAL_AUTOMATION_GENERATION_BATCH=5`

Estoque pronto considera `APROVADO + AGENDADO` com `final_image`.

O minimo e usado para saude/alerta. O alvo e o nivel operacional que a automacao tenta manter. Se o estoque estiver abaixo do alvo, a automacao gera no maximo um lote por tick, limitado ao que falta para chegar ao alvo.

## Scheduler

Os slots vem de `SocialProfile.horarios_publicacao`. O timezone do perfil e a fonte de verdade, normalmente `America/Sao_Paulo`.

O scheduler nao cria slots no passado e nao duplica horarios ja ocupados.

## Downtime

Se o sistema ficar parado, o tick nao publica tudo acumulado. Ele publica no maximo 1 por perfil e reagenda o restante para slots futuros, respeitando `SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES`.

## Retry

Retries automaticos sao conservadores. Erros ambiguos ficam em `ERRO` para revisao. O sistema prefere nao publicar a duplicar conteudo.

## Cron Render

Criar um Cron Job no painel Render:

- schedule: `*/5 * * * *`
- command: `python scripts/acionar_automacao_social.py`

O Cron precisa receber somente:

- `PLATFORM_BASE_URL`
- `SOCIAL_AUTOMATION_CRON_SECRET`

O valor de `SOCIAL_AUTOMATION_CRON_SECRET` deve ser o mesmo do Web Service.

O Cron nao precisa de `DATABASE_URL`, `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `MEDIA_ROOT` nem acesso ao Persistent Disk.

## Variaveis

- `SOCIAL_AUTOMATION_CRON_SECRET`
- `SOCIAL_AUTOMATION_QUEUE_MIN`
- `SOCIAL_AUTOMATION_QUEUE_TARGET`
- `SOCIAL_AUTOMATION_GENERATION_BATCH`
- `SOCIAL_AUTOMATION_MIN_POST_GAP_MINUTES`
- `SOCIAL_AUTOMATION_MAX_RETRIES`
- `SOCIAL_AUTOMATION_HARD_24H_CAP`
- `SOCIAL_AUTOMATION_TICK_LOCK_SECONDS`

## Configurar Laila

Dry-run:

`python manage.py configurar_automacao_social lailapistola --preset 20-dia --dry-run --settings=config.settings.prod`

Aplicar:

`python manage.py configurar_automacao_social lailapistola --preset 20-dia --apply --settings=config.settings.prod`

## Executar Manualmente

No sistema, staff/superuser pode usar o botao `Executar automacao agora` no detalhe do perfil.

## Pausar

Para pausar:

- alterar perfil para `SEMIAUTOMATICO`; ou
- desativar o perfil; ou
- remover/limpar `SOCIAL_AUTOMATION_CRON_SECRET` do Web Service.

## Diagnostico

Verificar logs:

- `social_automation.tick_start`
- `social_automation.profile_start`
- `social_automation.inventory`
- `social_automation.auto_generation_start`
- `social_automation.auto_generation_end`
- `social_automation.auto_publish_start`
- `social_automation.auto_publish_success`
- `social_automation.auto_publish_error`
- `social_automation.tick_end`
