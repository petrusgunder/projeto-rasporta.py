"""
API de Verificacao Fisica para Estacoes Raspberry Pi.
Garante:
- Autenticacao por credencial exclusiva da estacao (HMAC-SHA256)
- Protecao contra Replay Attack (Timestamp + Nonce unico com janela de 30s)
- Rate Limiting por estacao e por IP
- Sanitizacao de entrada e resposta minima (sem expor dados pessoais sensiveis)
- Registro de auditoria das verificacoes
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime
from banco_de_dados import get_db
from agenda import validar_acesso_fisico_codigo
from config_sistema import agora_campus
from usuarios import registrar_log_admin

IDENTIFICADOR_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")
CODIGO_BARRAS_REGEX = re.compile(r"^[a-zA-Z0-9._-]{1,50}$")

# Cache em memoria de nonces recentes: {nonce: expira_em_epoch}
_NONCES_USADOS: dict[str, float] = {}
JANELA_TIMESTAMP_SEGUNDOS = 30

# Rate limit: maximo 30 leituras por minuto por estacao/IP
_RATE_LIMIT_ESTACAO: dict[str, list[float]] = {}
MAX_REQ_POR_MINUTO = 30


def limpar_caches_temporarios() -> None:
    agora = time.time()
    expirados = [n for n, exp in _NONCES_USADOS.items() if exp <= agora]
    for n in expirados:
        _NONCES_USADOS.pop(n, None)


def verificar_rate_limit_api(chave: str) -> bool:
    agora = time.time()
    janela_inicio = agora - 60.0
    historico = [t for t in _RATE_LIMIT_ESTACAO.get(chave, []) if t >= janela_inicio]
    if len(historico) >= MAX_REQ_POR_MINUTO:
        _RATE_LIMIT_ESTACAO[chave] = historico
        return False
    historico.append(agora)
    _RATE_LIMIT_ESTACAO[chave] = historico
    return True


def mascarar_codigo_barras(codigo: str) -> str:
    limpo = (codigo or "").strip()
    if len(limpo) <= 4:
        return "*" * len(limpo)
    return f"{limpo[:2]}{'*' * (len(limpo) - 4)}{limpo[-2:]}"


def assinar_payload_estacao(
    station_id: str, timestamp_str: str, nonce: str, raw_body: bytes, segredo_hmac: str
) -> str:
    """Gera assinatura HMAC-SHA256 canonica."""
    mensagem = f"{station_id}\n{timestamp_str}\n{nonce}\n".encode("utf-8") + raw_body
    return hmac.new(segredo_hmac.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def cadastrar_estacao(
    identificador: str,
    nome: str,
    id_laboratorio: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str, str]:
    """
    Cadastra ou rotaciona credencial de uma estacao fisica.
    Retorna (sucesso, mensagem, segredo_gerado).
    """
    identificador = (identificador or "").strip()
    nome = (nome or "").strip()
    if not IDENTIFICADOR_REGEX.match(identificador):
        return False, "Identificador inválido (use 3 a 64 caracteres: letras, números, '-' ou '_').", ""
    if not nome:
        return False, "Informe o nome da estação.", ""

    segredo = secrets.token_hex(32)
    conn = get_db(db_path)
    try:
        with conn:
            lab = conn.execute("SELECT id, nome FROM Laboratorio WHERE id = ?", (id_laboratorio,)).fetchone()
            if not lab:
                return False, "Laboratório não encontrado.", ""

            existente = conn.execute(
                "SELECT id FROM EstacaoLeitura WHERE identificador = ?", (identificador,)
            ).fetchone()
            if existente:
                return False, "Já existe uma estação com este identificador.", ""

            conn.execute(
                "INSERT INTO EstacaoLeitura (identificador, nome, id_laboratorio, segredo_hmac, ativa) "
                "VALUES (?, ?, ?, ?, 1)",
                (identificador, nome, id_laboratorio, segredo),
            )
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "CADASTRAR_ESTACAO",
                f"Estação '{identificador}' ({nome}) vinculada ao laboratório '{lab['nome']}'.",
            )
        return True, "Estação cadastrada com sucesso.", segredo
    finally:
        conn.close()


def rotacionar_chave_estacao(
    id_estacao: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str, str]:
    novo_segredo = secrets.token_hex(32)
    conn = get_db(db_path)
    try:
        with conn:
            est = conn.execute(
                "SELECT identificador FROM EstacaoLeitura WHERE id = ?", (id_estacao,)
            ).fetchone()
            if not est:
                return False, "Estação não encontrada.", ""
            conn.execute(
                "UPDATE EstacaoLeitura SET segredo_hmac = ? WHERE id = ?",
                (novo_segredo, id_estacao),
            )
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "ROTACIONAR_CHAVE_ESTACAO",
                f"Chave HMAC da estação '{est['identificador']}' rotacionada.",
            )
        return True, "Chave rotacionada com sucesso.", novo_segredo
    finally:
        conn.close()


def alternar_status_estacao(
    id_estacao: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str]:
    conn = get_db(db_path)
    try:
        with conn:
            est = conn.execute(
                "SELECT identificador, ativa FROM EstacaoLeitura WHERE id = ?", (id_estacao,)
            ).fetchone()
            if not est:
                return False, "Estação não encontrada."
            novo_status = 0 if est["ativa"] else 1
            conn.execute("UPDATE EstacaoLeitura SET ativa = ? WHERE id = ?", (novo_status, id_estacao))
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "STATUS_ESTACAO",
                f"Estação '{est['identificador']}' alterada para {'ATIVA' if novo_status else 'INATIVA'}.",
            )
        return True, "Status da estação atualizado."
    finally:
        conn.close()


def listar_estacoes(db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            """
            SELECT e.id, e.identificador, e.nome, e.id_laboratorio, e.ativa, e.ultimo_contato,
                   l.nome AS lab_nome
            FROM EstacaoLeitura e
            JOIN Laboratorio l ON l.id = e.id_laboratorio
            ORDER BY e.id ASC
            """
        ).fetchall()
    finally:
        conn.close()


def listar_logs_verificacao(limite: int = 50, db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            """
            SELECT v.id, v.estacao_identificador, l.nome AS lab_nome, v.codigo_mascarado,
                   v.autorizado, v.motivo, v.criado_em
            FROM LogVerificacaoFisica v
            LEFT JOIN Laboratorio l ON l.id = v.id_laboratorio
            ORDER BY v.id DESC LIMIT ?
            """,
            (limite,),
        ).fetchall()
    finally:
        conn.close()


def inicializar_estacao_via_ambiente(db_path: str | None = None) -> None:
    """
    Permite provisionar a primeira estacao automaticamente via variaveis de ambiente:
      RASPORTA_STATION_ID, RASPORTA_STATION_SECRET, RASPORTA_STATION_LAB_ID
    """
    st_id = (os.environ.get("RASPORTA_STATION_ID") or "").strip()
    st_secret = (os.environ.get("RASPORTA_STATION_SECRET") or "").strip()
    st_lab_raw = (os.environ.get("RASPORTA_STATION_LAB_ID") or "").strip()
    if not (st_id and st_secret and st_lab_raw.isdigit() and len(st_secret) >= 32):
        return

    conn = get_db(db_path)
    try:
        with conn:
            existe = conn.execute(
                "SELECT id FROM EstacaoLeitura WHERE identificador = ?", (st_id,)
            ).fetchone()
            lab = conn.execute(
                "SELECT id FROM Laboratorio WHERE id = ?", (int(st_lab_raw),)
            ).fetchone()
            if not existe and lab:
                conn.execute(
                    "INSERT INTO EstacaoLeitura (identificador, nome, id_laboratorio, segredo_hmac, ativa) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (st_id, f"Estação {st_id}", int(st_lab_raw), st_secret),
                )
    finally:
        conn.close()


def processar_requisicao_verificacao(
    station_id: str,
    timestamp_str: str,
    nonce: str,
    assinatura_recebida: str,
    raw_body: bytes,
    dados_json: dict | None,
    ip_origem: str = "",
    momento_ref: datetime | None = None,
    db_path: str | None = None,
) -> tuple[int, dict]:
    """
    Valida criptograficamente a estacao, verifica autorizacao do codigo de barras
    no laboratorio vinculado e grava log de auditoria.
    Retorna (http_status, payload_resposta).
    """
    limpar_caches_temporarios()

    station_id = (station_id or "").strip()
    timestamp_str = (timestamp_str or "").strip()
    nonce = (nonce or "").strip()
    assinatura_recebida = (assinatura_recebida or "").strip().lower()

    if not station_id or not IDENTIFICADOR_REGEX.match(station_id):
        return 401, {"autorizado": False, "led": "vermelho", "erro": "Credenciais de estação ausentes ou inválidas."}

    if not verificar_rate_limit_api(f"{station_id}:{ip_origem}"):
        return 429, {"autorizado": False, "led": "vermelho", "erro": "Limite de requisições excedido."}

    if not timestamp_str.isdigit() or not nonce or len(nonce) < 12 or len(nonce) > 128 or not assinatura_recebida:
        return 401, {"autorizado": False, "led": "vermelho", "erro": "Cabeçalhos de segurança inválidos."}

    ts_req = int(timestamp_str)
    agora_epoch = int(time.time())
    if abs(agora_epoch - ts_req) > JANELA_TIMESTAMP_SEGUNDOS:
        return 401, {"autorizado": False, "led": "vermelho", "erro": "Requisição expirada (relógio dessincronizado)."}

    chave_nonce = f"{station_id}:{nonce}"
    if chave_nonce in _NONCES_USADOS:
        return 409, {"autorizado": False, "led": "vermelho", "erro": "Nonce já utilizado (replay bloqueado)."}

    conn = get_db(db_path)
    try:
        estacao = conn.execute(
            """
            SELECT e.id, e.identificador, e.id_laboratorio, e.segredo_hmac, e.ativa, l.nome AS lab_nome
            FROM EstacaoLeitura e
            JOIN Laboratorio l ON l.id = e.id_laboratorio
            WHERE e.identificador = ?
            """,
            (station_id,),
        ).fetchone()

        if not estacao or not estacao["ativa"]:
            return 403, {"autorizado": False, "led": "vermelho", "erro": "Estação não cadastrada ou desativada."}

        assinatura_esperada = assinar_payload_estacao(
            station_id, timestamp_str, nonce, raw_body, estacao["segredo_hmac"]
        )
        if not hmac.compare_digest(assinatura_esperada, assinatura_recebida):
            return 401, {"autorizado": False, "led": "vermelho", "erro": "Assinatura HMAC inválida."}

        # Registra nonce somente apos assinatura valida
        _NONCES_USADOS[chave_nonce] = agora_epoch + (JANELA_TIMESTAMP_SEGUNDOS * 2)

        if not isinstance(dados_json, dict):
            return 400, {"autorizado": False, "led": "vermelho", "erro": "Payload JSON inválido."}

        codigo_barras = str(dados_json.get("codigo_barras") or "").strip()
        if not codigo_barras or not CODIGO_BARRAS_REGEX.match(codigo_barras):
            return 400, {"autorizado": False, "led": "vermelho", "erro": "Código de barras inválido."}

        autorizado, detalhe = validar_acesso_fisico_codigo(
            codigo_barras,
            estacao["id_laboratorio"],
            momento=momento_ref,
            db_path=db_path,
        )

        usr_row = conn.execute(
            "SELECT id FROM SistemaUsuario WHERE codigo_barras = ?", (codigo_barras,)
        ).fetchone()
        usr_id = usr_row["id"] if usr_row else None

        with conn:
            conn.execute(
                "UPDATE EstacaoLeitura SET ultimo_contato = ? WHERE id = ?",
                (agora_campus().isoformat(timespec="seconds"), estacao["id"]),
            )
            conn.execute(
                """
                INSERT INTO LogVerificacaoFisica
                (estacao_identificador, id_laboratorio, codigo_mascarado, usuario_id, autorizado, motivo, ip_origem)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    estacao["identificador"],
                    estacao["id_laboratorio"],
                    mascarar_codigo_barras(codigo_barras),
                    usr_id,
                    1 if autorizado else 0,
                    detalhe,
                    ip_origem[:64],
                ),
            )

        # Resposta objetiva sem expor e-mail, ID interno ou nivel detalhado desnecessario
        return 200, {
            "autorizado": bool(autorizado),
            "led": "verde" if autorizado else "vermelho",
            "laboratorio": estacao["lab_nome"],
            "mensagem": "Acesso permitido" if autorizado else "Acesso negado",
        }
    finally:
        conn.close()