# Publicacao em producao

## 1. Dependencias
- Use um ambiente virtual novo para producao.
- Instale Django e um driver PostgreSQL compativel, por exemplo `psycopg[binary]`.

## 2. Variaveis de ambiente
- Copie `.env.example` e preencha os valores reais.
- Defina `DJANGO_SETTINGS_MODULE=config.settings.prod`.

## 3. Banco de dados
- Crie o banco PostgreSQL.
- Execute:

```powershell
venv\Scripts\python.exe manage.py migrate --settings=config.settings.prod
```

## 4. Usuario administrador
- Crie um superusuario:

```powershell
venv\Scripts\python.exe manage.py createsuperuser --settings=config.settings.prod
```

## 5. Arquivos estaticos
- Gere os arquivos estaticos:

```powershell
venv\Scripts\python.exe manage.py collectstatic --noinput --settings=config.settings.prod
```

## 6. Validacao de seguranca
- Rode o checklist oficial do Django:

```powershell
venv\Scripts\python.exe manage.py check --deploy --settings=config.settings.prod
```

## 7. Servidor
- Nao use `runserver` em producao.
- Publique com um servidor WSGI/ASGI e HTTPS na frente.
- Configure o proxy para enviar `X-Forwarded-Proto=https`.

## 8. Operacao
- Ative backup do PostgreSQL.
- Restrinja o acesso ao admin.
- Crie usuarios para diretoria e operacao.

## 9. Render
- O projeto ja possui `render.yaml` na raiz para uso com Blueprint.
- No Render, escolha `New +` -> `Blueprint` e conecte o repositorio do GitHub.
- O Render criara:
  - um `Web Service` Django
  - um banco `PostgreSQL`
- Apos o primeiro deploy:
  - rode `createsuperuser` no Shell do Render
  - ajuste o dominio proprio, se houver
  - atualize `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` com o dominio final

## 10. Midia enviada pelo sistema
- Os uploads atuais sao servidos pelo proprio Django.
- Em ambiente Render, arquivos enviados podem exigir `Persistent Disk` ou armazenamento externo para nao depender apenas do container.
