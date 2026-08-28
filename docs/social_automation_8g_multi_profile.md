# Automacao Social 8G - multiplos perfis Instagram

## Modelo

Cada `SocialProfile` pode possuir uma `SocialInstagramConnection` ativa. A conexao guarda `instagram_user_id`, `username`, tipo da conta, status de validacao e token criptografado.

O token nao deve ser exibido em UI, logs ou comandos. Em producao, configure:

```text
SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY=<fernet-key>
```

Gere a chave com:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Meta App

O sistema continua usando um unico Meta App. Cada conta profissional autoriza esse mesmo aplicativo.

Scopes usados:

```text
instagram_business_basic
instagram_business_content_publish
```

URL de callback implementada:

```text
https://dashboard-ambar.onrender.com/plataforma/automacoes/social/instagram/callback/
```

Configure essa URL nas configuracoes de Business Login for Instagram do Meta App.

## Rollout Laila

1. Fazer deploy com `SOCIAL_INSTAGRAM_LEGACY_FALLBACK=true`.
2. Configurar `SOCIAL_INSTAGRAM_TOKEN_ENCRYPTION_KEY` no Render.
3. Rodar:

```bash
python manage.py migrar_instagram_legacy_para_perfil lailapistola --dry-run
python manage.py migrar_instagram_legacy_para_perfil lailapistola --apply
```

4. Testar:

```bash
python manage.py testar_instagram --perfil lailapistola
python manage.py listar_conexoes_instagram
```

5. Validar publicacao normal da Laila.
6. Depois de confirmado, alterar `SOCIAL_INSTAGRAM_LEGACY_FALLBACK=false`.

## Primeiro novo perfil

1. Criar o `SocialProfile`.
2. Cadastrar personalidade, estilo e instrucoes IA.
3. Cadastrar imagens-base.
4. Configurar layout de foto e Reel.
5. Clicar em `Conectar Instagram`.
6. Autorizar a conta profissional no fluxo Meta.
7. Testar conexao.
8. Gerar conteudo.
9. Publicar uma foto ou Reel manual.
10. Configurar `posts_por_dia`, `reels_por_dia` e horarios.
11. Somente depois mudar para automatico.

## Referencias oficiais

- Business Login for Instagram: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
- Content Publishing: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing

Observacao: a documentacao atual da Meta indica Instagram API com Instagram Login para contas profissionais Business ou Creator, host `graph.instagram.com`, permissao `instagram_business_basic` para dados basicos e `instagram_business_content_publish` para publicacao.
