# Disaster Recovery

Este runbook define a estrategia inicial de backup e recuperacao do Sistema de Obras em operacao SaaS assistida.

## Estado Atual

- Banco de dados: PostgreSQL no Render, configurado por `DATABASE_URL`.
- Arquivos: disco persistente do Render montado em `/var/data`, com `MEDIA_ROOT=/var/data/media`.
- Storage Django: `FileSystemStorage`.
- Backups externos: nao comprovados pelo repositorio.
- Restore completo: nao comprovado em ambiente real.

O Persistent Disk nao e backup. Ele reduz perda em deploy, mas continua sendo o disco operacional.

## Metas Iniciais

- RPO alvo: 24 horas para banco e midia.
- RTO alvo: 4 horas para incidente comum com backup valido disponivel.
- Drill de restore: mensal no inicio do piloto e antes de liberar clientes pagantes sem acompanhamento.

Estes valores sao metas operacionais internas, nao SLA comercial.

## Backup do Banco

Gerar dump PostgreSQL em formato custom:

```bash
python scripts/backup_database.py
```

Requisitos:

- `DATABASE_URL` configurada no ambiente.
- `pg_dump` disponivel no `PATH`.
- `pg_restore` recomendado para validacao estrutural.

Saida padrao:

```text
backups/database/dashboard-db-YYYYMMDD-HHMMSS.dump
```

O script:

- nao imprime `DATABASE_URL`;
- falha se `DATABASE_URL` estiver ausente;
- falha se `pg_dump` falhar;
- gera arquivo temporario e so promove para o nome final depois de validar;
- valida com `pg_restore --list` quando disponivel;
- confirma que o dump nao ficou vazio.

## Restore do Banco

Nunca testar restore sobre producao.

Procedimento recomendado em banco temporario:

```bash
createdb dashboard_restore_drill
pg_restore --clean --if-exists --no-owner --no-acl --dbname dashboard_restore_drill backups/database/dashboard-db-YYYYMMDD-HHMMSS.dump
python manage.py migrate --settings=config.settings.prod
python manage.py check --settings=config.settings.prod
```

Para restaurar em incidente real:

1. Congelar a aplicacao ou colocar o servico em manutencao.
2. Identificar o dump mais recente valido.
3. Criar novo banco ou limpar banco de destino conforme decisao operacional.
4. Executar `pg_restore` no banco de destino.
5. Atualizar `DATABASE_URL` somente se o banco restaurado for novo.
6. Rodar migrations.
7. Subir aplicacao.
8. Executar checklist pos-restore.

## Backup de Media

Gerar archive compactado de `MEDIA_ROOT`:

```bash
python scripts/backup_media.py --media-root /var/data/media
```

Saida padrao:

```text
backups/media/dashboard-media-YYYYMMDD-HHMMSS.tar.gz
```

O script:

- nao apaga arquivos de origem;
- falha se `MEDIA_ROOT` nao existir;
- gera arquivo temporario antes do arquivo final;
- valida se o `tar.gz` pode ser aberto.

## Restore de Media

Procedimento:

```bash
mkdir -p /var/data
tar -xzf backups/media/dashboard-media-YYYYMMDD-HHMMSS.tar.gz -C /var/data
```

Estrutura esperada apos restore:

```text
/var/data/media/
```

Validar:

- `MEDIA_ROOT` aponta para `/var/data/media`;
- arquivos de diario de obra abrem para usuario autorizado;
- arquivos privados retornam 404/403 para usuario sem acesso;
- imagens da Automacao Social continuam disponiveis nas rotas assinadas.

## Backup Offsite

Manter segunda copia fora do Render. Opcoes recomendadas:

- Object storage compativel com S3: baixo custo, versionamento, lifecycle e criptografia.
- Storage dedicado de backup: simples de operar, bom para retencao, menos integrado ao app.

Escolha inicial recomendada: S3 compativel com versionamento, criptografia em repouso e lifecycle.

Nao conectar provedor externo sem decisao operacional e credenciais dedicadas.

## Retencao Inicial

- Diario: 7 copias.
- Semanal: 4 copias.
- Mensal: 6 copias.

Para o piloto, isso equilibra custo e capacidade de voltar a pontos recentes.

## Criptografia

- Transito: usar TLS para acesso ao Render/PostgreSQL.
- Repouso: depender da criptografia do provedor para banco/disco.
- Backups offsite: exigir criptografia do bucket/storage e acesso por credencial minima.
- Opcional antes de copiar para terceiros: criptografar artefatos com ferramenta operacional aprovada.

Nunca armazenar secrets, tokens ou `DATABASE_URL` dentro dos arquivos versionados.

## Monitoramento

Verificar em cada execucao:

- arquivo foi criado;
- tamanho maior que zero;
- dump validou com `pg_restore --list` quando disponivel;
- archive de media abre com `tar`;
- espaco livre suficiente antes e depois;
- copia offsite concluiu;
- alerta caso o backup diario nao apareca.

Implementacao simples inicial: checklist diario no Render + alerta manual. Evolucao recomendada: job agendado com notificacao para e-mail/Sentry.

## Runbook de Incidente

1. Declarar incidente e horario de inicio.
2. Pausar publicacoes/agendamentos que possam gerar escrita.
3. Identificar ponto de recuperacao desejado.
4. Restaurar banco em ambiente temporario.
5. Restaurar media correspondente.
6. Rodar migrations.
7. Rodar `python manage.py check`.
8. Validar login e tenants.
9. Validar arquivos privados.
10. Validar PDFs/relatorios.
11. Apontar producao para o banco/media restaurados.
12. Registrar perda estimada de dados e causa raiz.

## QA Pos-Restore

- Login de superuser.
- Login de usuario de empresa.
- Seletor mostra apenas empresas vinculadas.
- Dashboard da empresa abre sem dados de outro tenant.
- Obra abre.
- Medicao abre e gera PDF.
- Financeiro abre e gera relatorio.
- Diario abre.
- Foto de diario abre para usuario autorizado.
- Arquivo privado falha para usuario sem acesso.
- Troca de empresa bloqueia tenant nao vinculado.
- Automacao Social lista conteudos para staff.
- Healthcheck responde OK.

## Acoes Manuais no Render

1. Confirmar plano e politica de backup do Render Postgres.
2. Executar primeiro `pg_dump` manual em shell seguro.
3. Executar primeiro backup de `/var/data/media`.
4. Copiar ambos para storage offsite.
5. Executar restore drill em banco temporario.
6. Documentar data, responsavel, duracao e resultado.
