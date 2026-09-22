from billing.models import Assinatura


def assinatura_atual(empresa):
    if not empresa:
        return None
    return (
        Assinatura.objects.filter(empresa=empresa)
        .order_by('-criado_em')
        .first()
    )


def empresa_tem_acesso(empresa, agora=None):
    assinatura = assinatura_atual(empresa)
    if assinatura is None:
        return True
    assinatura.avaliar_suspensao(agora=agora)
    return assinatura.permite_acesso(agora=agora)


def motivo_bloqueio(empresa, agora=None):
    assinatura = assinatura_atual(empresa)
    if assinatura is None or empresa_tem_acesso(empresa, agora=agora):
        return ''
    if assinatura.status == Assinatura.Status.SUSPENSA:
        return 'Assinatura suspensa.'
    if assinatura.status == Assinatura.Status.EM_ATRASO:
        return 'Assinatura em atraso fora do periodo de tolerancia.'
    return 'Assinatura pendente.'
