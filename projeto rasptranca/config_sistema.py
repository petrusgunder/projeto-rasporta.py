"""
Configuracoes centralizadas do Rasporta / RaspTranca - IFSC Campus Garopaba.
"""
import os
import secrets
from datetime import datetime, time
from zoneinfo import ZoneInfo

FUSO_CAMPUS = ZoneInfo("America/Sao_Paulo")

# Estrutura detalhada dos periodos academicos.
# O turno noturno (19:00 as 22:00) possui intervalo oficial de 20 minutos (20:20 - 20:40),
# dividido em dois blocos efetivos de aula/reserva: Periodo 8 (19:00 - 20:20) e Periodo 9 (20:40 - 22:00).
CONFIG_PERIODOS = {
    1: {"turno": "matutino", "inicio": "08:00", "fim": "08:55"},
    2: {"turno": "matutino", "inicio": "09:00", "fim": "09:50"},
    3: {"turno": "matutino", "inicio": "10:10", "fim": "11:05"},
    4: {"turno": "matutino", "inicio": "11:10", "fim": "12:00"},
    5: {"turno": "vespertino", "inicio": "13:30", "fim": "14:25"},
    6: {"turno": "vespertino", "inicio": "14:30", "fim": "15:20"},
    7: {"turno": "vespertino", "inicio": "15:40", "fim": "16:35"},
    8: {"turno": "noturno", "inicio": "19:00", "fim": "20:20"},
    9: {"turno": "noturno", "inicio": "20:40", "fim": "22:00"},
}

INTERVALOS_BLOQUEADOS = [
    {"turno": "noturno", "inicio": "20:20", "fim": "20:40", "duracao_min": 20},
]

PERIODOS = {
    num: f"{dados['inicio']} - {dados['fim']}"
    for num, dados in CONFIG_PERIODOS.items()
}


def obter_secret_key(base_dir: str) -> str:
    """
    Obtem a SECRET_KEY de variavel de ambiente.
    Caso nao esteja definida, gera e persiste localmente uma chave criptografica
    em arquivo oculto (.secret_key) fora do controle de versao.
    """
    env_key = os.environ.get("RASPORTA_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if env_key and len(env_key.strip()) >= 24:
        return env_key.strip()

    key_file = os.path.join(base_dir, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            chave = f.read().strip()
            if chave:
                return chave

    nova_chave = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(nova_chave)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return nova_chave


def agora_campus() -> datetime:
    """Retorna data e hora atuais no fuso horario oficial do IFSC Garopaba."""
    return datetime.now(FUSO_CAMPUS)


def _parse_hora(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(hour=h, minute=m)


def periodo_ja_comecou_hoje(periodo: int, momento: datetime | None = None) -> bool:
    """Retorna True se o horario de inicio do periodo ja foi atingido ou ultrapassado hoje."""
    dados = CONFIG_PERIODOS.get(periodo)
    if not dados:
        return True
    ref = momento or agora_campus()
    inicio = _parse_hora(dados["inicio"])
    return (ref.hour, ref.minute) >= (inicio.hour, inicio.minute)


def periodo_ativo_no_momento(momento: datetime | None = None) -> int | None:
    """
    Retorna o numero do periodo em andamento no momento informado,
    ou None se estiver fora do horario de aula ou durante o intervalo noturno (20:20-20:40).
    """
    ref = momento or agora_campus()
    atual = ref.time().replace(tzinfo=None)

    for intervalo in INTERVALOS_BLOQUEADOS:
        if _parse_hora(intervalo["inicio"]) <= atual < _parse_hora(intervalo["fim"]):
            return None

    for num, dados in CONFIG_PERIODOS.items():
        inicio = _parse_hora(dados["inicio"])
        fim = _parse_hora(dados["fim"])
        if inicio <= atual <= fim:
            return num
    return None