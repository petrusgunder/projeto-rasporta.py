import hmac
import secrets
import time
from functools import wraps
from flask import session, redirect, url_for, request, flash, abort
from traducoes import traduzir

# Controle em memoria de tentativas de login por chave (IP + email)
_TENTATIVAS_LOGIN: dict[str, dict] = {}
MAX_TENTATIVAS = 5
JANELA_BLOQUEIO_SEGUNDOS = 300  # 5 minutos


def obter_idioma_atual() -> str:
    return session.get("idioma", "pt")


def gerar_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validar_csrf_token(token_recebido: str | None) -> bool:
    token_sessao = session.get("_csrf_token")
    if not token_sessao or not token_recebido:
        return False
    return hmac.compare_digest(str(token_sessao), str(token_recebido))


def verificar_bloqueio_login(identificador: str) -> tuple[bool, int]:
    """Retorna (bloqueado, segundos_restantes)."""
    registro = _TENTATIVAS_LOGIN.get(identificador)
    if not registro:
        return False, 0
    agora = time.time()
    bloqueado_ate = registro.get("bloqueado_ate", 0)
    if bloqueado_ate > agora:
        return True, int(bloqueado_ate - agora) + 1
    if agora - registro.get("ultima_falha", 0) > JANELA_BLOQUEIO_SEGUNDOS:
        _TENTATIVAS_LOGIN.pop(identificador, None)
    return False, 0


def registrar_falha_login(identificador: str) -> None:
    agora = time.time()
    registro = _TENTATIVAS_LOGIN.get(identificador, {"contagem": 0, "ultima_falha": agora, "bloqueado_ate": 0})
    if agora - registro["ultima_falha"] > JANELA_BLOQUEIO_SEGUNDOS:
        registro["contagem"] = 0
    registro["contagem"] += 1
    registro["ultima_falha"] = agora
    if registro["contagem"] >= MAX_TENTATIVAS:
        registro["bloqueado_ate"] = agora + JANELA_BLOQUEIO_SEGUNDOS
    _TENTATIVAS_LOGIN[identificador] = registro


def limpar_falhas_login(identificador: str) -> None:
    _TENTATIVAS_LOGIN.pop(identificador, None)


def login_usuario_required(funcao):
    """Exige que o usuario esteja autenticado no Sistema de Agenda."""
    @wraps(funcao)
    def decorada(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return decorada


def admin_required(funcao):
    """Exige que o usuario logado seja administrador (comum ou principal)."""
    @wraps(funcao)
    def decorada(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("login"))
        if session.get("usuario_nivel_admin") not in ("admin", "super_admin"):
            flash(traduzir("msg_acesso_negado", obter_idioma_atual()), "erro")
            return redirect(url_for("home"))
        return funcao(*args, **kwargs)
    return decorada


def super_admin_required(funcao):
    """Exige que o usuario logado seja Administrador Principal (super_admin)."""
    @wraps(funcao)
    def decorada(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("login"))
        if session.get("usuario_nivel_admin") != "super_admin":
            flash(traduzir("msg_apenas_super_admin", obter_idioma_atual()), "erro")
            return redirect(url_for("admin_dashboard"))
        return funcao(*args, **kwargs)
    return decorada