# Operacao de producao SaaS assistida

Este documento cobre a rotina minima para operar o sistema em producao no Render durante o piloto SaaS assistido.

## Monitoramento

- Configurar `SENTRY_DSN` no Render para ativar captura de excecoes.
- Manter `SENTRY_ENVIRONMENT=production`.
- Manter `SENTRY_TRACES_SAMPLE_RATE=0` no inicio do piloto para reduzir custo e ruido.
- Verificar eventos novos apos cada deploy e apos cada acesso externo relevante.

## Logging

- Logs estruturados saem no stdout/stderr do Render.
- Nivel padrao: `DJANGO_LOG_LEVEL=INFO`.
- Erros de requisicao e falhas de SMTP/health check sao registrados sem expor senhas.

## Health check

Endpoint:

```text
/healthz/
```

Resposta saudavel:

```json
{"status": "ok", "database": "ok"}
```

Resposta com falha de banco:

```json
{"status": "error", "database": "unavailable"}
```

O Render deve continuar usando `/healthz/` como health check.

## Rate limit

Limites configuraveis por ambiente:

```text
LOGIN_RATE_LIMIT=10
LOGIN_RATE_LIMIT_WINDOW=300
PASSWORD_RESET_RATE_LIMIT=5
PASSWORD_RESET_RATE_LIMIT_WINDOW=3600
INVITE_RATE_LIMIT=20
INVITE_RATE_LIMIT_WINDOW=3600
```

A implementacao atual usa o cache padrao do Django. Em ambiente com multiplos workers, o limite e por processo quando usado `LocMemCache`. Para escala comercial, trocar para Redis ou outro cache compartilhado.

## SMTP

Variaveis obrigatorias:

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=
SERVER_EMAIL=
PLATFORM_BASE_URL=https://dominio-do-sistema
PLATFORM_SUPPORT_EMAIL=
```

Teste manual:

```bash
python manage.py testar_email destinatario@exemplo.com --settings=config.settings.prod
```

## Backup do banco

Para o piloto, usar backup gerenciado do Render Postgres quando disponivel no plano contratado.

Rotina minima:

- Antes de alteracoes grandes: gerar backup manual pelo painel do Render.
- Semanalmente: confirmar se backups automaticos estao ativos no plano.
- Mensalmente: testar restauracao em banco temporario.

Com `pg_dump`, quando houver acesso operacional:

```bash
pg_dump "$DATABASE_URL" > backup-dashboard.sql
```

Nunca commitar arquivos de backup no Git.

## Backup de midia

O sistema ainda usa disco persistente do Render para `DJANGO_MEDIA_ROOT`.

Rotina minima:

- Confirmar se o disco persistente esta montado em `/var/data`.
- Exportar copia periodica de `/var/data/media`.
- Guardar copia fora do Render.
- Testar abertura de arquivos restaurados.

Para versao comercial, migrar midia para storage externo com backup e lifecycle, como S3 compativel.

## RPO / RTO sugeridos para piloto

- RPO banco: ate 24 horas.
- RTO banco: ate 4 horas.
- RPO midia: ate 24 horas.
- RTO midia: ate 8 horas.

Estes numeros sao aceitaveis para piloto assistido, mas devem ser reduzidos antes de venda ampla.

## Checklist primeiro cliente

- [ ] `DJANGO_DEBUG=False`.
- [ ] `DJANGO_SECRET_KEY` forte configurada.
- [ ] `DJANGO_ALLOWED_HOSTS` com dominio correto.
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` com HTTPS correto.
- [ ] SMTP testado com `testar_email`.
- [ ] `PLATFORM_BASE_URL` configurado com HTTPS.
- [ ] `SENTRY_DSN` configurado.
- [ ] `/healthz/` retornando banco `ok`.
- [ ] Superuser tecnico validado.
- [ ] Cliente criado pelo onboarding assistido.
- [ ] Administrador do cliente recebeu convite.
- [ ] Administrador do cliente definiu senha.
- [ ] Usuario cliente nao acessa outra empresa.
- [ ] PDF principal gerado com identidade visual correta.
- [ ] Upload/download de midia testado.
- [ ] Backup do banco confirmado.
- [ ] Backup de midia confirmado.

## Incidentes

1. Verificar status do Render e eventos do servico.
2. Verificar logs recentes.
3. Verificar Sentry.
4. Testar `/healthz/`.
5. Se banco indisponivel, verificar Render Postgres e conexao `DATABASE_URL`.
6. Se midia indisponivel, verificar disco persistente e `DJANGO_MEDIA_ROOT`.
7. Registrar acao tomada e horario.

## Pendencias para SaaS comercial

- Cache compartilhado para rate limit.
- Backup automatizado de midia fora do Render.
- Politica formal de retencao de backups.
- Auditoria estruturada de eventos de usuario.
- Monitoramento de uptime externo.
- Politica de resposta a incidentes.
