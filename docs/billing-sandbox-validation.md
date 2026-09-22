# Validacao manual do billing no Mercado Pago

Este roteiro valida a integracao da Estribo com o Mercado Pago sem efetuar
cobranca real. Use exclusivamente credenciais, conta compradora e cartoes de
teste fornecidos pelo Mercado Pago.

## Limites desta validacao

- Nao usar Access Token, Public Key, usuario ou cartao de producao.
- Nao registrar credenciais em prints, tickets, logs ou commits.
- Nao testar parcelamento como se fosse uma funcionalidade contratada.
- Nao ativar manualmente uma assinatura durante os testes de webhook, pois isso
  esconderia falhas da integracao.
- Executar um caso por assinatura para manter a evidencia facil de auditar.

## Variaveis de ambiente

| Variavel | Necessaria | Valor para validacao | Uso atual |
| --- | --- | --- | --- |
| `MERCADOPAGO_ACCESS_TOKEN` | Sim | Access Token de teste da aplicacao | Autentica chamadas server-side para `/preapproval`, pagamentos e cancelamento |
| `MERCADOPAGO_PUBLIC_KEY` | Recomendada | Public Key de teste da mesma aplicacao | Reservada para integracao client-side; o fluxo atual nao a consome |
| `MERCADOPAGO_WEBHOOK_SECRET` | Sim | Assinatura secreta da configuracao de Webhooks | Valida `x-signature` sem expor a credencial |
| `MERCADOPAGO_ENVIRONMENT` | Sim | `test` | Mantem o sistema fora do modo `production`; nao seleciona credenciais nem troca o host da API |
| `BILLING_GRACE_DAYS` | Sim | `5` | Define a tolerancia apos pagamento recusado |
| `DJANGO_ALLOWED_HOSTS` | Conforme hospedagem | Incluir o hostname publico do tunel, sem esquema | Permite que o Django aceite a requisicao encaminhada pelo tunel |

O Mercado Pago usa `https://api.mercadopago.com` tanto para chamadas com
credenciais de teste quanto de producao. Portanto, `MERCADOPAGO_ENVIRONMENT=test`
nao cria sozinho um sandbox: a protecao contra cobranca real depende de
`MERCADOPAGO_ACCESS_TOKEN` e `MERCADOPAGO_PUBLIC_KEY` serem inequivocamente as
credenciais de teste da aplicacao.

Antes de iniciar, confirme no painel do Mercado Pago que as credenciais foram
copiadas da area **Credenciais de teste**. Nao tente inferir o ambiente apenas
pelo nome da variavel ou pelo endpoint.

## Configuracao do webhook

URL publica:

```text
https://HOST-PUBLICO/billing/webhooks/mercadopago/
```

Configurar na aplicacao do Mercado Pago os eventos:

- `subscription_preapproval`;
- `subscription_authorized_payment`;
- `payment`.

Copiar a assinatura secreta gerada nessa configuracao para
`MERCADOPAGO_WEBHOOK_SECRET`. A URL precisa ser HTTPS, publicamente acessivel e
encaminhar POST, query string e os headers `x-signature` e `x-request-id` sem
alteracao.

A rota e `csrf_exempt`, nao exige login e responde JSON. Nao ha impedimento
estrutural ao uso de tunel. Se o tunel apontar diretamente para uma instancia
Django local, inclua seu hostname em `DJANGO_ALLOWED_HOSTS` e reinicie o
processo. `DJANGO_CSRF_TRUSTED_ORIGINS` nao e necessario para este POST
especifico. Nao proteja a URL com Basic Auth, tela de confirmacao do tunel ou
login intermediario.

Smoke sem evento real:

1. Um GET deve retornar `405 Method Not Allowed`.
2. Um POST sem assinatura valida deve retornar `403` quando o secret estiver
   configurado.
3. Um webhook legitimo deve retornar `200` com `status=processed` ou
   `status=ignored` quando repetido.
4. Conferir o evento em Django Admin, modelo `EventoWebhook`, ou pelo shell sem
   exibir o payload integral se ele contiver dados pessoais.

## Contas e dados de teste

1. Na aplicacao Mercado Pago, criar ou selecionar um usuario vendedor de teste.
2. Criar um usuario comprador de teste do mesmo pais.
3. Usar no sistema uma empresa e um lead claramente identificados como teste.
4. O e-mail do lead deve ser o e-mail do comprador de teste aceito pelo fluxo.
5. Usar somente cartoes e identidades de teste publicados pelo Mercado Pago.
6. Para simular resultados, usar o nome do titular indicado pela documentacao:
   `APRO` para aprovado, `OTHE` para recusado e `CONT` para pendente.

Referencias oficiais:

- Credenciais de teste: https://www.mercadopago.com.br/developers/en/docs/checkout-pro-orders/resources/credentials
- Contas de teste: https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/test-accounts
- Cartoes de teste para assinaturas: https://www.mercadopago.com.br/developers/en/docs/subscriptions/additional-content/your-integrations/test/cards
- Webhooks: https://www.mercadopago.com.br/developers/en/docs/wix/additional-content/your-integrations/notifications/webhooks

## Onde iniciar no painel Estribo

O operador precisa ser `is_staff` ou superuser.

1. Acessar `/plataforma/leads/`.
2. Abrir o lead de teste.
3. Clicar em **Preparar contratacao**.
4. Selecionar a empresa de teste ja criada no onboarding.
5. Selecionar Mensal, Semestral ou Anual.
6. Clicar em **Preparar checkout**.
7. No detalhe da assinatura, conferir periodicidade, valor, status `Pendente`,
   Gateway ID e link **Abrir checkout**.
8. A lista geral fica em `/plataforma/assinaturas/` ou no link **Assinaturas**
   da navegacao staff.

Se o Gateway ID ou o checkout estiverem vazios, nao prossiga. Confira a
mensagem apresentada, a credencial de teste e o log sanitizado da chamada.

## Teste mensal

Resultado esperado logo apos **Preparar checkout**:

- periodicidade local: `Mensal`;
- valor local: `R$ 149,90`;
- payload remoto: `frequency=1`, `frequency_type=months`;
- moeda: `BRL`;
- status local inicial: `Pendente`;
- Gateway ID e checkout preenchidos.

Concluir um checkout com comprador e cartao de teste. Apos a confirmacao
aprovada, conferir no detalhe:

- assinatura `Ativa`;
- um pagamento `Aprovado` de R$ 149,90;
- inicio preenchido;
- fim do periodo e proxima cobranca aproximadamente um mes depois;
- evento de webhook processado uma unica vez.

## Teste semestral

Resultado esperado logo apos **Preparar checkout**:

- periodicidade local: `Semestral`;
- valor local: `R$ 799,00`;
- payload remoto: `frequency=6`, `frequency_type=months`;
- status local inicial: `Pendente`;
- Gateway ID e checkout preenchidos.

Apos pagamento aprovado, conferir pagamento de R$ 799,00 e proxima cobranca
aproximadamente seis meses depois. Nao selecionar parcelamento para contornar o
modelo recorrente.

## Teste anual

Resultado esperado logo apos **Preparar checkout**:

- periodicidade local: `Anual`;
- valor local: `R$ 1.399,00`;
- payload remoto: `frequency=12`, `frequency_type=months`;
- status local inicial: `Pendente`;
- Gateway ID e checkout preenchidos.

Apos pagamento aprovado, conferir pagamento de R$ 1.399,00 e proxima cobranca
aproximadamente doze meses depois. Nao selecionar parcelamento para contornar o
modelo recorrente.

## Pagamento aprovado

1. Usar o cenario oficial `APRO` no checkout de teste.
2. Aguardar o webhook `payment`.
3. Conferir resposta HTTP 200.
4. No detalhe da assinatura, conferir pagamento `Aprovado`, valor correto,
   forma de pagamento e identificador do gateway.
5. Conferir assinatura `Ativa`, datas de periodo e ausencia de tolerancia.
6. Atualizar a pagina apenas depois do webhook; nao usar **Ativar manualmente**.

## Pagamento recusado

1. Criar outra assinatura de teste e usar o cenario oficial `OTHE`.
2. Aguardar o webhook `payment`.
3. Conferir pagamento `Recusado`.
4. Conferir assinatura `Em atraso`.
5. Conferir `grace_until` em aproximadamente cinco dias.
6. Durante a tolerancia, confirmar que o acesso da empresa continua permitido.

## Pagamento pendente

1. Criar outra assinatura de teste e usar o cenario oficial `CONT`.
2. Aguardar o webhook `payment`.
3. Conferir pagamento `Pendente` ou `Em processamento`, conforme o status real
   retornado pelo gateway.
4. A assinatura nao deve ser ativada por um pagamento ainda nao aprovado.
5. Registrar a evolucao posterior do mesmo pagamento para confirmar a
   atualizacao pelo identificador do gateway.

## Eventos de assinatura

Registrar para cada notificacao: tipo, ID do recurso, HTTP retornado, status do
`EventoWebhook` e efeito local.

Estado auditado antes da validacao real:

- `payment`: consulta `/v1/payments/{id}` e aplica status ao pagamento e a
  assinatura;
- `subscription_preapproval`: consulta `/preapproval/{id}` e sincroniza o
  estado da assinatura;
- `subscription_authorized_payment`: consulta `/authorized_payments/{id}` e
  normaliza a fatura, o `preapproval_id` e o pagamento tradicional aninhado.

Validar que `subscription_authorized_payment` e `payment`, em qualquer ordem,
representem uma unica cobranca e gerem somente um `Pagamento` local.

## Idempotencia

1. Capturar apenas o ID e o tipo de um webhook legitimo recebido.
2. Usar a funcao de reenvio do painel Mercado Pago para o mesmo evento, sem
   fabricar assinatura.
3. A primeira entrega deve responder `status=processed`.
4. A repeticao deve responder `status=ignored` com o mesmo `event_id`.
5. Deve existir apenas um `EventoWebhook` para `gateway + event_id`.
6. Deve existir apenas um `Pagamento` para assinatura + gateway + ID do
   pagamento; o valor nao pode ser duplicado.

## Cancelamento

No detalhe da assinatura existe o botao **Cancelar ao fim do periodo**. Use-o
somente em uma assinatura descartavel de teste.

O pedido apenas marca `cancel_at_period_end=True` localmente. Como o Mercado
Pago nao oferece agendamento nativo para o fim do ciclo, nenhuma chamada de
cancelamento e feita nesse momento e o acesso permanece ativo.

Executar periodicamente:

```bash
python manage.py process_billing_cancellations
```

O comando cancela no gateway dentro dos 60 minutos anteriores ao fim do periodo
e encerra o acesso local apenas em `data_fim_periodo`. O intervalo do Cron Job
deve ser menor que essa janela para impedir uma renovacao indevida.

No teste controlado, conferir:

- resposta sem erro na interface;
- `cancel_at_period_end=True` e `canceled_at` preenchido localmente;
- status real da assinatura no Mercado Pago;
- ausencia de nova cobranca no gateway;
- resultado da reconciliacao posterior;
- estado local ainda `Ativa` entre o cancelamento remoto antecipado e o fim do
  periodo;
- estado local `Cancelada` depois da data final.

## Reconciliacao

Executar primeiro para uma unica assinatura:

```bash
python manage.py reconcile_billing --assinatura ID_LOCAL
```

Conferir a saida sem expor credenciais. O comando consulta
`/preapproval/{gateway_subscription_id}` e sincroniza:

- `authorized`/`active` para `Ativa`;
- `paused` para `Em atraso`, com tolerancia;
- `cancelled`/`canceled` para `Cancelada`.

Depois do teste unitario, executar:

```bash
python manage.py reconcile_billing
```

Uma indisponibilidade externa deve preservar o estado local e gerar aviso. O
comando atual reconcilia o estado da assinatura, nao importa historico de
pagamentos ausentes.

## Parcelamento

Esta validacao nao autoriza nem promete parcelamento de assinatura. Para os
planos semestral e anual, validar somente a recorrencia de R$ 799,00 a cada seis
meses e R$ 1.399,00 a cada doze meses. Nao criar parcelas manualmente, nao
alterar payload e nao interpretar opcoes incidentais do checkout como garantia
comercial de recorrencia parcelada.

## Checklist GO/NO-GO

- [ ] Credenciais confirmadas visualmente como **de teste** no painel Mercado Pago.
- [ ] Vendedor e comprador de teste sao contas distintas e do mesmo pais.
- [ ] `MERCADOPAGO_ENVIRONMENT=test` configurado.
- [ ] `MERCADOPAGO_WEBHOOK_SECRET` configurado e POST sem assinatura rejeitado.
- [ ] URL HTTPS publica aceita POST e preserva query string e headers.
- [ ] Host do tunel incluido em `DJANGO_ALLOWED_HOSTS`, quando aplicavel.
- [ ] Mensal criou `frequency=1`, valor R$ 149,90 e checkout de teste.
- [ ] Semestral criou `frequency=6`, valor R$ 799,00 e checkout de teste.
- [ ] Anual criou `frequency=12`, valor R$ 1.399,00 e checkout de teste.
- [ ] Pagamento aprovado ativou assinatura e registrou um pagamento.
- [ ] Pagamento recusado criou tolerancia sem bloquear imediatamente.
- [ ] Pagamento pendente nao ativou assinatura.
- [ ] Reenvio do mesmo webhook nao duplicou evento nem pagamento.
- [ ] Reconciliacao individual preservou ou corrigiu o estado esperado.
- [ ] Reconciliacao global terminou sem alterar indevidamente clientes legados.
- [ ] Nenhuma cobranca, credencial, conta ou cartao real foi utilizado.
- [ ] Parcelamento nao foi prometido nem simulado por workaround.
- [ ] `subscription_authorized_payment` e `payment` produziram uma unica cobranca local.
- [ ] Cron de cancelamento executou antes da renovacao e preservou acesso ate o fim.

Resultado atual da auditoria estatica: os bloqueadores de codigo foram
corrigidos. A validacao manual completa em sandbox continua obrigatoria antes
do go-live de producao.
