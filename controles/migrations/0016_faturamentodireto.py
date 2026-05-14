from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('obras', '0006_carrega_dados_orla_lami'),
        ('controles', '0015_alter_notafiscalordemcomprageral_conta_pagar'),
    ]

    operations = [
        migrations.CreateModel(
            name='FaturamentoDireto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero_nf', models.CharField(max_length=80, verbose_name='Nr da NF')),
                ('empresa_comprou', models.CharField(max_length=180, verbose_name='Empresa que comprou')),
                ('valor_nota', models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='Valor da nota fiscal')),
                ('descricao', models.CharField(max_length=255, verbose_name='Descricao do que foi comprado')),
                ('vencimento_boleto', models.DateField(verbose_name='Vencimento do boleto')),
                ('medicao_desconto', models.CharField(blank=True, max_length=120, verbose_name='Medicao em que foi descontada')),
                ('observacoes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('obra', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='faturamentos_diretos', to='obras.obra')),
            ],
            options={
                'verbose_name': 'Faturamento direto',
                'verbose_name_plural': 'Faturamentos diretos',
                'ordering': ['-vencimento_boleto', '-id'],
            },
        ),
    ]
