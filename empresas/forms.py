from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from obras.models import Obra

from .models import Empresa, UsuarioEmpresa


User = get_user_model()
GRUPOS_FUNCIONAIS = ['Administrador', 'Diretoria', 'Financeiro', 'Engenharia', 'Compras', 'Administrativo', 'Obras', 'Consulta']


def grupos_funcionais_queryset():
    return Group.objects.filter(name__in=GRUPOS_FUNCIONAIS).order_by('name')


def _css_class_for_widget(widget):
    if isinstance(widget, (forms.Select, forms.SelectMultiple)):
        return 'form-select'
    if isinstance(widget, forms.CheckboxInput):
        return 'form-check-input'
    return 'form-control'


class UsuarioEmpresaCriacaoForm(forms.Form):
    username = forms.CharField(label='Usuario', max_length=150)
    first_name = forms.CharField(label='Nome', max_length=150, required=False)
    last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=False)
    password = forms.CharField(
        label='Senha temporaria',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Defina uma senha temporaria manual. O usuario podera troca-la em Minha area.',
    )
    grupo = forms.ModelChoiceField(label='Grupo/Função', queryset=Group.objects.none(), required=False)
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
        super().__init__(*args, **kwargs)
        self.fields['grupo'].queryset = grupos_funcionais_queryset()
        self.fields['obras_permitidas'].queryset = (
            Obra.objects.filter(empresa=empresa).order_by('nome_obra') if empresa else Obra.objects.none()
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', _css_class_for_widget(field.widget))

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ja existe um usuario com este username.')
        return username

    def save(self):
        user = User(
            username=self.cleaned_data['username'],
            first_name=self.cleaned_data.get('first_name', ''),
            last_name=self.cleaned_data.get('last_name', ''),
            email=self.cleaned_data.get('email', ''),
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        user.set_password(self.cleaned_data['password'])
        user.save()
        vinculo = UsuarioEmpresa.objects.create(
            usuario=user,
            empresa=self.empresa,
            grupo=self.cleaned_data.get('grupo'),
            administrador_empresa=self.cleaned_data.get('administrador_empresa', False),
            ativo=True,
        )
        vinculo.obras_permitidas.set(self.cleaned_data.get('obras_permitidas'))
        return vinculo


class UsuarioEmpresaVinculoForm(forms.ModelForm):
    first_name = forms.CharField(label='Nome', max_length=150, required=False)
    last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=False)

    class Meta:
        model = UsuarioEmpresa
        fields = ['grupo', 'administrador_empresa', 'ativo', 'obras_permitidas']
        labels = {
            'grupo': 'Grupo/Função',
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
