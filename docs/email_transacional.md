# E-mail transacional

O sistema usa SMTP generico configurado por variaveis de ambiente. Nao ha provider hardcoded nem credenciais no repositorio.

## Local

Para desenvolvimento, o backend padrao imprime os e-mails no console quando `DJANGO_DEBUG=True`:

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
PLATFORM_NAME=Sistema de Obras
PLATFORM_BASE_URL=http://localhost:8000
DEFAULT_FROM_EMAIL=nao-responda@localhost
```

## Render/producao

Configurar no painel do Render:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.seuprovedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=usuario-smtp
EMAIL_HOST_PASSWORD=valor-secreto
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL=nao-responda@seudominio.com
SERVER_EMAIL=nao-responda@seudominio.com
PLATFORM_NAME=Sistema de Obras
PLATFORM_BASE_URL=https://seudominio.com
PLATFORM_SUPPORT_EMAIL=suporte@seudominio.com
```

## Fluxos

- Reset de senha: tela de login -> Esqueci minha senha -> e-mail -> nova senha.
- Convite: Minha Empresa -> Usuarios -> Convidar usuario -> e-mail -> definir senha.
- Usuario existente com senha: recebe aviso de acesso e usa a senha atual.
- Usuario pendente: pode receber reenvio de convite pela listagem da empresa.

Os links usam tokens nativos do Django e respeitam `PASSWORD_RESET_TIMEOUT`.
