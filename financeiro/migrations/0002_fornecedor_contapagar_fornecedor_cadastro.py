import django.db.models.deletion
import csv
from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def carregar_credores(apps, schema_editor):
    Fornecedor = apps.get_model('financeiro', 'Fornecedor')
    csv_path = Path(settings.BASE_DIR) / 'financeiro' / 'data' / 'credores.csv'
    if not csv_path.exists():
        return
    with csv_path.open(encoding='utf-8', newline='') as arquivo:
        for row in csv.DictReader(arquivo):
            nome = (row.get('nome') or '').strip()
            if not nome:
                continue
            cpf_cnpj = (row.get('cpf_cnpj') or '').strip()
            Fornecedor.objects.update_or_create(
                nome=nome,
                cpf_cnpj=cpf_cnpj,
                defaults={
                    'ie_identidade': (row.get('ie_identidade') or '').strip(),
                    'endereco': (row.get('endereco') or '').strip(),
                    'municipio': (row.get('municipio') or '').strip(),
                    'cep': (row.get('cep') or '').strip(),
                    'telefone': (row.get('telefone') or '').strip(),
                    'ativo': True,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Fornecedor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=180)),
                ('cpf_cnpj', models.CharField(blank=True, max_length=30)),
                ('ie_identidade', models.CharField(blank=True, max_length=40)),
                ('endereco', models.CharField(blank=True, max_length=255)),
                ('municipio', models.CharField(blank=True, max_length=120)),
                ('cep', models.CharField(blank=True, max_length=20)),
                ('telefone', models.CharField(blank=True, max_length=40)),
                ('ativo', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Fornecedor',
                'verbose_name_plural': 'Fornecedores',
                'ordering': ['nome'],
                'constraints': [models.UniqueConstraint(fields=('nome', 'cpf_cnpj'), name='unique_fornecedor_nome_documento')],
            },
        ),
        migrations.AddField(
            model_name='contapagar',
            name='fornecedor_cadastro',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='contas_pagar', to='financeiro.fornecedor'),
        ),
        migrations.RunPython(carregar_credores, migrations.RunPython.noop),
    ]
