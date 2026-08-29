# Fase 8H - Motor generico de carrosseis

## Objetivo

A automacao social passa a suportar `carousel` como terceiro tipo de midia, ao lado de `image` e `reel`.
O recurso e generico por perfil social e nao depende de uma persona especifica.

## Configuracao por perfil

`SocialProfile` controla o mix diario:

- `posts_por_dia`: total diario.
- `reels_por_dia`: parte do total reservada para Reels.
- `carousels_por_dia`: parte do total reservada para carrosseis.
- `fotos_por_dia`: calculado como `posts - reels - carousels`.

O default de `carousels_por_dia` e `0`, preservando o comportamento de perfis existentes.

## Templates

`SocialCarouselTemplate` define a linguagem visual do carrossel:

- proporcao quadrada ou retrato;
- fundo solido, gradiente ou imagem;
- cores;
- alinhamentos;
- marcadores de perfil, rodape e numero do slide.

## Slides

`SocialCarouselSlide` pertence a um `SocialContent` do tipo `carousel`.
O carrossel precisa ter de 2 a 10 slides ativos.

Cada slide pode ter:

- tipo: capa, conteudo ou CTA;
- titulo;
- corpo;
- imagem fonte opcional;
- imagem renderizada;
- container Instagram filho e fingerprint.

## Renderizacao

`renderizar_midia_social()` despacha automaticamente:

- foto para `renderizar_conteudo_social`;
- Reel para `renderizar_reel_social`;
- carrossel para `renderizar_carrossel_social`.

Cada slide e renderizado como JPEG valido em:

- 1080 x 1080 para quadrado;
- 1080 x 1350 para retrato.

## Instagram

A publicacao de carrossel segue o fluxo:

1. criar um container filho por slide com `is_carousel_item=true`;
2. criar container pai com `media_type=CAROUSEL`;
3. publicar o container pai com `media_publish`.

As URLs de slide usam rota assinada:

`/social-media/ig-carousel/<content_id>/<slide_id>/<signature>.jpg`

## Idempotencia

O fingerprint do conteudo considera:

- hashes dos slides renderizados;
- ordem dos slides;
- tipo de midia;
- caption;
- Instagram User ID.

Cada slide tambem possui fingerprint proprio para reutilizacao segura do container filho.

## Geração de imagem por IA

A fundacao existe em `social_automation/image_generation.py`, mas a chamada real permanece desabilitada por padrao.
Para habilitar futuramente, configurar:

- `OPENAI_SOCIAL_IMAGE_MODEL`;
- `OPENAI_SOCIAL_IMAGE_QUALITY`;
- `SocialProfile.ai_image_generation_enabled`.

## Comandos

- `diagnosticar_mix_diario`: mostra fotos, Reels e carrosseis planejados.
- `diagnosticar_render_carrossel`: renderiza um carrossel localmente.
- `diagnosticar_container_carrossel_instagram`: cria containers filhos/pai para diagnostico, sem publicar.
