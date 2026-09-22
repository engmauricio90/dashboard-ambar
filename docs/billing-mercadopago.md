# Billing Estribo + Mercado Pago

## Objetivo

Esta camada prepara a Estribo para assinaturas recorrentes por empresa, com checkout assistido, webhooks idempotentes, tolerancia de pagamento e reconciliacao segura.

O fluxo comercial continua assistido:

1. lead solicita demonstracao;
2. equipe qualifica o lead;
3. cliente e empresa sao criados no onboarding assistido;
4. equipe prepara a contratacao vinculada a uma empresa existente;
5. Mercado Pago confirma pagamento/autorizacao via webhook;
6. assinatura fica ativa.

## Variaveis de ambiente

Obrigatorias para validacao real em sandbox/producao:

- `MERCADOPAGO_ACCESS_TOKEN`
- `MERCADOPAGO_PUBLIC_KEY`
- `MERCADOPAGO_WEBHOOK_SECRET`
- `MERCADOPAGO_ENVIRONMENT`

Configuracao operacional:

- `BILLING_GRACE_DAYS`, padrao `5`.

As credenciais nao devem ser commitadas, impressas em log ou renderizadas em HTML.

## Oferta

Plano unico Estribo:

- mensal: R$ 149,90, cobranca a cada 1 mes;
- semestral: R$ 799,00, cobranca a cada 6 meses;
- anual: R$ 1.399,00, cobranca a cada 12 meses.

Os valores sao tratados internamente com `Decimal`.

## Parcelamento

A documentacao oficial consultada confirma criacao de assinaturas pelo endpoint `/preapproval`, com valor e frequencia em `auto_recurring`.

Nao foi encontrada evidencia tecnica suficiente, nesta fase, de que uma assinatura recorrente semestral/anual possa ser cobrada nativamente em 3 parcelas sem juros mantendo a recorrencia automatica do Mercado Pago.

Por isso:

- o checkout recorrente nao promete parcelamento;
- nao foi criado workaround manual;
- a condicao comercial de parcelamento deve ser validada no sandbox antes de ser prometida no fluxo de pagamento.

## Webhooks

Endpoint:

```text
/billing/webhooks/mercadopago/
```

O processamento e idempotente por `gateway + event_id`.

Em producao, a validacao exige `MERCADOPAGO_WEBHOOK_SECRET` e compara a assinatura recebida em `x-signature` por HMAC SHA-256. Em sandbox/testes, sem segredo configurado, a rota pode aceitar chamadas para permitir validacao controlada.

Quando o evento referencia pagamento, o sistema tenta buscar o recurso no gateway antes de aplicar o status. Se o gateway estiver indisponivel, o evento permanece como recebido e o estado da assinatura nao e rebaixado.

Cada evento consulta seu recurso oficial separadamente:

- `payment`: `GET /v1/payments/{id}`;
- `subscription_authorized_payment`: `GET /authorized_payments/{id}`;
- `subscription_preapproval`: `GET /preapproval/{id}`.

O pagamento autorizado e normalizado usando o ID da fatura, o
`preapproval_id` e, quando presente, o ID do pagamento tradicional aninhado.
Assim, a chegada posterior do webhook `payment` atualiza a mesma cobranca em vez
de criar outro registro local.

## Estados

Assinatura:

- `PENDENTE`
- `ATIVA`
- `EM_ATRASO`
- `SUSPENSA`
- `CANCELADA`
- `EXPIRADA`

Pagamento:

- `PENDENTE`
- `APROVADO`
- `RECUSADO`
- `CANCELADO`
- `ESTORNADO`
- `EM_PROCESSAMENTO`

## Tolerancia

Falha de pagamento coloca a assinatura em `EM_ATRASO` e define `grace_until` com 5 dias por padrao.

Durante a tolerancia, o acesso continua normal.

Se o prazo expirar, a assinatura passa para `SUSPENSA` e o middleware bloqueia modulos operacionais sem apagar dados.

Pagamento aprovado recupera a assinatura para `ATIVA` e limpa a tolerancia.

## Cancelamento ao fim do periodo

O Mercado Pago documenta apenas pausa ou cancelamento no momento da chamada a
`PUT /preapproval/{id}`; nao foi encontrado agendamento nativo de cancelamento
para o fim do ciclo ja pago.

Por isso, o pedido feito no painel marca `cancel_at_period_end=True`, preserva o
acesso ate `data_fim_periodo` e nao chama o gateway imediatamente. O comando
abaixo deve ser executado periodicamente para cancelar antes da renovacao e
encerrar o estado local somente ao fim do periodo:

```bash
python manage.py process_billing_cancellations
```

Por padrao, a chamada ao gateway ocorre nos 60 minutos anteriores ao fim. A
antecedencia pode ser alterada com `--lead-minutes 120`. O comando e idempotente
e, se o gateway falhar, preserva o estado local para uma nova tentativa. Em
producao, o intervalo do Render Cron Job deve ser menor que a antecedencia.

## Empresas existentes

Empresas sem registro de assinatura sao tratadas como legado/grandfathered e continuam com acesso permitido.

Isso evita bloquear clientes existentes ao introduzir billing.

## Reconciliacao

Comando:

```bash
python manage.py reconcile_billing
python manage.py reconcile_billing --assinatura 123
```

Falha externa no Mercado Pago preserva o estado local e emite aviso. A reconciliacao nao suspende clientes por indisponibilidade do gateway.

Quando o cancelamento ao fim do periodo ja foi enviado ao gateway, a
reconciliacao preserva `ATIVA` ate `data_fim_periodo`. Um cancelamento remoto
sem agendamento local continua encerrando a assinatura.
