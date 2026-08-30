# Fase 8I - IA visual e carrossel autonomo

Esta fase transforma a automacao social em uma plataforma generica por perfil, sem regra fixa para nicho, pessoa ou tema.

## Politica por perfil

Cada `SocialProfile` controla sua propria IA visual:

- `ai_image_generation_enabled`: liga ou desliga a geracao visual no perfil.
- `ai_image_mode`: politica operacional.
- `ai_image_daily_limit`: limite diario do perfil; `0` usa o limite padrao.
- `ai_generated_images_reusable`: define se imagens geradas entram no banco reutilizavel.
- `image_ai_instructions`: instrucoes visuais especificas daquele perfil.

Politicas:

- `NONE`: sem geracao de imagem por IA.
- `BANK_ONLY`: usa somente imagens-base cadastradas.
- `AI_WHEN_NEEDED`: tenta banco primeiro; se o score for baixo, gera imagem.
- `AI_ALWAYS`: prefere gerar imagem quando houver quota.

Perfis existentes continuam conservadores: IA visual desativada por padrao.

## Pipeline de carrossel autonomo

1. A IA gera um blueprint estruturado com hook, caption, hashtags e slides.
2. Cada slide recebe `semantic_visual_intent`, `media_intent`, `media_required` e `preferred_layout`.
3. O `media_resolver` decide se usa imagem do banco, layout textual ou geracao de imagem.
4. Quando permitido pela politica, `image_generation` gera uma nova `SocialBaseImage`.
5. `image_analysis` pode analisar a imagem e criar regioes protegidas automaticas.
6. O `VisualComposer` escolhe a composicao segura.
7. O renderer cria os slides finais.
8. O conteudo fica sempre como rascunho.

## Variaveis de ambiente

- `OPENAI_API_KEY`
- `OPENAI_SOCIAL_MODEL`
- `OPENAI_SOCIAL_IMAGE_MODEL`
- `OPENAI_SOCIAL_IMAGE_QUALITY`
- `OPENAI_SOCIAL_VISION_MODEL`
- `OPENAI_SOCIAL_MODERATION_MODEL`
- `SOCIAL_MEDIA_MATCH_MIN_SCORE`
- `SOCIAL_IMAGE_ANALYSIS_MIN_CONFIDENCE`
- `SOCIAL_AI_IMAGE_MAX_PER_TICK`
- `SOCIAL_AI_IMAGE_MAX_PER_PROFILE_PER_DAY`
- `SOCIAL_AI_IMAGE_MAX_BYTES`

## Comandos

Diagnostico seco da geracao:

```bash
python manage.py diagnosticar_geracao_imagem_social <perfil>
```

Geracao real de uma imagem:

```bash
python manage.py diagnosticar_geracao_imagem_social <perfil> --generate
```

Diagnostico seco da analise:

```bash
python manage.py diagnosticar_analise_imagem_social <base_image_id>
```

Persistir analise:

```bash
python manage.py diagnosticar_analise_imagem_social <base_image_id> --persist
```

Gerar carrossel como rascunho:

```bash
python manage.py gerar_carrossel_ia <perfil> --tema "tema opcional" --slides 6
```

Nenhum comando publica no Instagram.
