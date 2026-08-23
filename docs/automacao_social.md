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
