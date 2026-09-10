from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from obras.models import Obra

from .models import Empresa, UsuarioEmpresa
from .services import gerar_username_por_email


User = get_user_model()
GRUPOS_FUNCIONAIS = ['Administrador', 'Diretoria', 'Financeiro', 'Engenharia', 'Compras', 'Administrativo', 'Obras', 'Consulta']
MAX_BRANDING_IMAGE_SIZE = 5 * 1024 * 1024


def grupos_funcionais_queryset():
    return Group.objects.filter(name__in=GRUPOS_FUNCIONAIS).order_by('name')


def _css_class_for_widget(widget):
    if isinstance(widget, (forms.Select, forms.SelectMultiple)):
        return 'form-select'
    if isinstance(widget, forms.CheckboxInput):
        return 'form-check-input'
    return 'form-control'


class UsuarioEmpresaCriacaoForm(forms.Form):
    username = forms.CharField(
        label='Usuario',
        max_length=150,
        required=False,
        help_text='Opcional para usuarios novos. Se ficar vazio, o sistema gera a partir do e-mail.',
    )
    first_name = forms.CharField(label='Nome', max_length=150, required=False)
    last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=True)
    grupo = forms.ModelChoiceField(label='Grupo/Funcao', queryset=Group.objects.none(), required=False)
    administrador_empresa = forms.BooleanField(label='Administrador da empresa', required=False)
    obras_permitidas = forms.ModelMultipleChoiceField(
        label='Obras permitidas',
        queryset=Obra.objects.none(),
        required=False,
        help_text='Se ficar vazio, os modulos atuais consideram acesso geral dentro da empresa.',
        widget=forms.SelectMultiple(attrs={'size': 8}),
    )

    def __init__(self, *args, empresa=None, **kwargs):
        self.empresa = empresa
        self.usuario_existente = None
        super().__init__(*args, **kwargs)
        self.fields['grupo'].queryset = grupos_funcionais_queryset()
        self.fields['obras_permitidas'].queryset = (
            Obra.objects.filter(empresa=empresa).order_by('nome_obra') if empresa else Obra.objects.none()
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', _css_class_for_widget(field.widget))
        self.fields['email'].widget.attrs.setdefault('autocomplete', 'email')

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ja existe um usuario com este username.')
        return username

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        usuarios = list(User.objects.filter(email__iexact=email).order_by('id'))
        if len(usuarios) > 1:
            raise forms.ValidationError('Existe mais de uma conta com este e-mail. Regularize antes de convidar.')
        if usuarios:
            self.usuario_existente = usuarios[0]
            if UsuarioEmpresa.objects.filter(usuario=self.usuario_existente, empresa=self.empresa).exists():
                raise forms.ValidationError('Este usuario ja possui vinculo com esta empresa.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        if self.usuario_existente and username and username.lower() != self.usuario_existente.username.lower():
            self.add_error('username', 'Este e-mail ja pertence a outro usuario. Deixe o campo usuario vazio.')
        return cleaned_data

    def save(self):
        user = self.usuario_existente
        usuario_criado = False
        if user is None:
            user = User(
                username=self.cleaned_data.get('username') or gerar_username_por_email(self.cleaned_data['email']),
                first_name=self.cleaned_data.get('first_name', ''),
                last_name=self.cleaned_data.get('last_name', ''),
                email=self.cleaned_data['email'],
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            user.set_unusable_password()
            user.save()
            usuario_criado = True
        vinculo = UsuarioEmpresa.objects.create(
            usuario=user,
            empresa=self.empresa,
            grupo=self.cleaned_data.get('grupo'),
            administrador_empresa=self.cleaned_data.get('administrador_empresa', False),
            ativo=True,
        )
        vinculo.obras_permitidas.set(self.cleaned_data.get('obras_permitidas'))
        return vinculo, usuario_criado


class OnboardingClienteForm(forms.Form):
    nome = forms.CharField(label='Nome da empresa', max_length=160)
    razao_social = forms.CharField(label='Razao social', max_length=180, required=False)
    cnpj = forms.CharField(label='CNPJ', max_length=20, required=False)
    email = forms.EmailField(label='E-mail da empresa', required=False)
    telefone = forms.CharField(label='Telefone', max_length=40, required=False)
    cidade = forms.CharField(label='Cidade', max_length=120, required=False)
    estado = forms.CharField(label='UF', max_length=2, required=False)
    cep = forms.CharField(label='CEP', max_length=20, required=False)

    admin_first_name = forms.CharField(label='Nome do administrador', max_length=150, required=False)
    admin_last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    admin_email = forms.EmailField(label='E-mail do administrador', required=True)
    admin_grupo = forms.ModelChoiceField(label='Grupo/Funcao', queryset=Group.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario_existente = None
        self.fields['admin_grupo'].queryset = grupos_funcionais_queryset()
        diretoria = self.fields['admin_grupo'].queryset.filter(name='Diretoria').first()
        if diretoria:
            self.fields['admin_grupo'].initial = diretoria
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', _css_class_for_widget(field.widget))
        self.fields['email'].widget.attrs.setdefault('autocomplete', 'email')
        self.fields['admin_email'].widget.attrs.setdefault('autocomplete', 'email')

    def clean_nome(self):
        nome = self.cleaned_data['nome'].strip()
        if Empresa.objects.filter(nome__iexact=nome).exists():
            raise forms.ValidationError('Ja existe uma empresa com este nome.')
        return nome

    def clean_cnpj(self):
        cnpj = (self.cleaned_data.get('cnpj') or '').strip()
        if cnpj and Empresa.objects.filter(cnpj__iexact=cnpj).exists():
            raise forms.ValidationError('Ja existe uma empresa com este CNPJ.')
        return cnpj

    def clean_admin_email(self):
        email = (self.cleaned_data.get('admin_email') or '').strip().lower()
        usuarios = list(User.objects.filter(email__iexact=email).order_by('id'))
        if len(usuarios) > 1:
            raise forms.ValidationError('Existe mais de uma conta com este e-mail. Regularize antes de continuar.')
        if usuarios:
            self.usuario_existente = usuarios[0]
        return email


class UsuarioEmpresaVinculoForm(forms.ModelForm):
    first_name = forms.CharField(label='Nome', max_length=150, required=False)
    last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=False)

    class Meta:
        model = UsuarioEmpresa
        fields = ['grupo', 'administrador_empresa', 'ativo', 'obras_permitidas']
        labels = {
            'grupo': 'Grupo/Funcao',
            'administrador_empresa': 'Administrador da empresa',
            'ativo': 'Ativo nesta empresa',
            'obras_permitidas': 'Obras permitidas',
        }
        widgets = {
            'obras_permitidas': forms.SelectMultiple(attrs={'size': 8}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        self.empresa = empresa
        super().__init__(*args, **kwargs)
        self.fields['grupo'].queryset = grupos_funcionais_queryset()
        self.fields['obras_permitidas'].queryset = (
            Obra.objects.filter(empresa=empresa).order_by('nome_obra') if empresa else Obra.objects.none()
        )
        self.fields['first_name'].initial = self.instance.usuario.first_name
        self.fields['last_name'].initial = self.instance.usuario.last_name
        self.fields['email'].initial = self.instance.usuario.email
        self.fields['email'].widget.attrs.setdefault('autocomplete', 'email')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', _css_class_for_widget(field.widget))

    def save(self, commit=True):
        vinculo = super().save(commit=False)
        usuario = vinculo.usuario
        usuario.first_name = self.cleaned_data.get('first_name', '')
        usuario.last_name = self.cleaned_data.get('last_name', '')
        usuario.email = self.cleaned_data.get('email', '')
        if commit:
            usuario.save(update_fields=['first_name', 'last_name', 'email'])
            vinculo.save()
            self.save_m2m()
        return vinculo


class IdentidadeVisualEmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            'logo',
            'cabecalho_documentos',
            'rodape_documentos',
            'texto_rodape',
            'cor_primaria',
            'cor_secundaria',
            'razao_social',
            'nome_fantasia',
            'cnpj',
            'endereco',
            'cidade',
            'estado',
            'cep',
            'telefone',
            'email',
            'responsavel_tecnico',
            'crea_responsavel',
        ]
        widgets = {
            'texto_rodape': forms.Textarea(attrs={'rows': 3}),
            'cor_primaria': forms.TextInput(attrs={'type': 'color'}),
            'cor_secundaria': forms.TextInput(attrs={'type': 'color'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = 'form-control'
            if isinstance(field.widget, forms.ClearableFileInput):
                css_class = 'form-control'
            field.widget.attrs.setdefault('class', css_class)

    def _clean_branding_image(self, field_name):
        image = self.cleaned_data.get(field_name)
        if image and getattr(image, 'size', 0) > MAX_BRANDING_IMAGE_SIZE:
            raise ValidationError('Envie uma imagem com no maximo 5 MB.')
        return image

    def clean_logo(self):
        return self._clean_branding_image('logo')

    def clean_cabecalho_documentos(self):
        return self._clean_branding_image('cabecalho_documentos')

    def clean_rodape_documentos(self):
        return self._clean_branding_image('rodape_documentos')


class ClientePlataformaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ['nome', 'razao_social', 'cnpj', 'email', 'telefone', 'cidade', 'estado', 'cep', 'ativa']
        labels = {
            'nome': 'Nome da empresa',
            'razao_social': 'Razao social',
            'cnpj': 'CNPJ',
            'email': 'E-mail',
            'telefone': 'Telefone',
            'cidade': 'Cidade',
            'estado': 'UF',
            'cep': 'CEP',
            'ativa': 'Empresa ativa',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', _css_class_for_widget(field.widget))
