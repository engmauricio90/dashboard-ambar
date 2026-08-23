# Onboarding assistido de cliente

Esta area e interna da plataforma e nao pertence a um tenant.

## Quem pode acessar

Somente usuarios tecnicos com `is_staff=True` ou `is_superuser=True`.

Administradores de empresa com `administrador_empresa=True` nao acessam a area de onboarding se nao forem staff/superuser.

URL:

```text
/plataforma/clientes/
```

## Como criar cliente

1. Acesse `Clientes`.
2. Clique em `Novo cliente`.
3. Informe os dados principais da empresa.
4. Informe nome, e-mail e grupo do primeiro administrador.
5. Salve.

O sistema cria:

- `Empresa` ativa;
- `User` novo com senha inutilizavel, se o e-mail ainda nao existir;
- ou reutiliza o `User` existente se houver exatamente uma conta com o e-mail;
- `UsuarioEmpresa` como `administrador_empresa=True`;
- convite por e-mail para definicao de senha, quando necessario.

## Reenvio de convite

Na pagina do cliente, usuarios com convite pendente exibem a acao `Reenviar convite`.

Falha SMTP nao desfaz a empresa nem o vinculo. O convite fica pendente para reenvio.

## Checklist operacional

Depois de criar o cliente:

1. Confirmar convite recebido.
2. Completar identidade visual.
3. Criar primeira obra.
4. Configurar usuarios adicionais.
5. Validar acesso.
6. Validar SMTP, backup e monitoramento.

## Observacoes

Nao ha cadastro publico, trial, plano, cobranca ou impersonation nesta fase.

Nao criar vinculo silencioso do operador tecnico com a empresa do cliente apenas para navegar no tenant.
