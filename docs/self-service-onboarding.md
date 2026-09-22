# Self-service e onboarding automatico Estribo

## Fluxo publico

1. A landing envia a periodicidade e a atribuicao para `/assinar/`.
2. O servidor valida dados, consentimento, honeypot e rate limit.
3. Um `CheckoutIntent` e criado sem criar `Empresa`.
4. O backend resolve o preco central e cria `/preapproval` no Mercado Pago.
5. O navegador e redirecionado somente para o `init_point` oficial.
6. O retorno publico apresenta o estado interno, mas nunca confirma pagamento
   por parametros GET.
7. O webhook consulta o recurso no gateway e e a autoridade financeira.
8. Somente um status aprovado/autorizado converte a intent.

## CheckoutIntent

`CheckoutIntent` representa uma tentativa anterior ao tenant. A URL publica usa
UUID e a `external_reference` opaca segue `estribo_checkout_<uuid>`, sem e-mail,
CNPJ ou outra PII. A intent guarda periodicidade, dados de contato,
consentimento e atribuicao. Nao guarda senha nem dados de cartao.

Estados: `INICIADO`, `CHECKOUT_CRIADO`, `AGUARDANDO_PAGAMENTO`, `PAGO`,
`CONVERTIDO`, `FALHOU`, `CANCELADO` e `EXPIRADO`.

## Mercado Pago

Os valores sao resolvidos em `billing.services.comercial`; o browser envia
somente a periodicidade. `PUBLIC_BASE_URL` gera a back URL HTTPS sem confiar no
Host da requisicao. Em `MERCADOPAGO_ENVIRONMENT=test`, somente o payload remoto
usa `MERCADOPAGO_TEST_PAYER_EMAIL` ou `test@testuser.com`; o e-mail informado
permanece intacto na intent.

Os eventos `payment`, `subscription_authorized_payment` e
`subscription_preapproval` reutilizam o endpoint e o service layer existentes.
O retorno do navegador nao converte a intent.

## Conversao e idempotencia

`converter_checkout_intent()` usa `transaction.atomic` e `select_for_update`.
Uma intent terminal `CONVERTIDO` nao volta a `PAGO`, portanto webhooks repetidos
ou eventos payment/authorized relacionados nao criam outro tenant.

A conversao reutiliza `empresas.services.criar_cliente_assistido()` e cria:

- uma `Empresa` ativa;
- um usuario com senha inutilizavel, sem staff ou superuser;
- um `UsuarioEmpresa` administrador apenas da nova empresa;
- uma `Assinatura` vinculada a empresa e a intent.

Nao ha deduplicacao de empresa por nome. A garantia e a conversao unica da
intent. E-mail ja existente interrompe uma conversao ambigua sem criar empresa.

## Primeiro acesso e e-mail

O convite usa o token nativo de definicao de senha do Django. Nenhuma senha e
armazenada, exibida ou enviada. O envio ocorre depois da transacao; falha SMTP
nao desfaz nem duplica o onboarding em uma nova entrega do webhook.

Em producao, `PLATFORM_BASE_URL` ou `PUBLIC_BASE_URL`, SMTP e remetente precisam
estar configurados. Se o envio falhar, o staff pode reenviar o convite pelo
painel existente de clientes.

## Atribuicao e analytics

UTM, gclid, fbclid e referrer sao persistidos na intent. O JavaScript conserva
a primeira origem na sessao e envia eventos sem PII: `pricing_start_checkout`,
`checkout_form_start`, `checkout_form_submit`, `checkout_redirect`,
`checkout_return` e `subscription_confirmed`. Scripts externos continuam
dependentes do consentimento de cookies.

## Seguranca e falhas

- CSRF, validacao server-side, honeypot e rate limit protegem o formulario.
- UUID evita enumeracao da URL publica.
- Falha do gateway mantem a intent auditavel e nao cria tenant.
- Checkout abandonado nao cria tenant e pode reutilizar o `init_point` salvo.
- Webhook duplicado e conversao duplicada sao idempotentes.
- Secrets e IDs completos do gateway nao aparecem nas paginas publicas.
- Clientes legados sem assinatura continuam com a politica de acesso atual.

## Sandbox e producao

Sandbox exige credenciais de teste, `MERCADOPAGO_ENVIRONMENT=test`,
`MERCADOPAGO_TEST_PAYER_EMAIL`, webhook assinado e `PUBLIC_BASE_URL` apontando
para o HTTPS publico do tunel. Producao deve usar o dominio oficial e credenciais
de producao somente depois da validacao integral do fluxo self-service.

## Parcelamento

Recorrencia com parcelamento em 3 vezes nao foi comprovada. O checkout promete
apenas renovacao automatica conforme o ciclo. Condicoes parceladas permanecem
no fluxo assistido, sem workaround no billing recorrente.
