"""
CRUD dos Laboratorios, Reservas Simples e Recorrentes e Validacao Temporal de Acesso.
"""
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from banco_de_dados import get_db
from config_sistema import (
    PERIODOS,
    CONFIG_PERIODOS,
    agora_campus,
    periodo_ja_comecou_hoje,
    periodo_ativo_no_momento,
)
from usuarios import registrar_log_admin


def CriarLabsPadrao(db_path: str | None = None) -> None:
    """Cria laboratorios iniciais caso a tabela esteja vazia."""
    conn = get_db(db_path)
    try:
        with conn:
            qtd = conn.execute("SELECT COUNT(*) FROM Laboratorio").fetchone()[0]
            if qtd == 0:
                labs = [
                    ("Lab Info 1", "Laboratório de Informática Principal", 30),
                    ("Lab Info 2", "Laboratório de Informática Secundário", 25),
                    ("Lab Redes", "Laboratório de Redes e Hardware", 20),
                ]
                conn.executemany(
                    "INSERT INTO Laboratorio (nome, descricao, capacidade) VALUES (?, ?, ?)",
                    labs,
                )
    finally:
        conn.close()


# ---------- LABORATORIOS ----------

def ListarLaboratorios(db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, nome, descricao, capacidade FROM Laboratorio ORDER BY nome ASC"
        ).fetchall()
    finally:
        conn.close()


def BuscarLaboratorio(id_lab: int, db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, nome, descricao, capacidade FROM Laboratorio WHERE id = ?",
            (id_lab,),
        ).fetchone()
    finally:
        conn.close()


def CadastrarLaboratorio(
    nome: str,
    descricao: str,
    capacidade: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str]:
    nome = (nome or "").strip()
    descricao = (descricao or "").strip()
    if not nome:
        return False, "Informe o nome do laboratório."
    cap = capacidade if (isinstance(capacidade, int) and capacidade > 0) else 30

    conn = get_db(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO Laboratorio (nome, descricao, capacidade) VALUES (?, ?, ?)",
                (nome, descricao, cap),
            )
            registrar_log_admin(
                conn, executor_id, executor_nome, "CADASTRAR_LAB", f"Laboratório '{nome}' cadastrado."
            )
        return True, "Laboratório cadastrado com sucesso."
    except sqlite3.IntegrityError:
        return False, "Já existe um laboratório cadastrado com este nome."
    finally:
        conn.close()


def EditarLaboratorio(
    id_lab: int,
    nome: str,
    descricao: str,
    capacidade: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str]:
    nome = (nome or "").strip()
    descricao = (descricao or "").strip()
    if not nome:
        return False, "O nome do laboratório não pode ficar vazio."
    cap = capacidade if (isinstance(capacidade, int) and capacidade > 0) else 30

    conn = get_db(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE Laboratorio SET nome = ?, descricao = ?, capacidade = ? WHERE id = ?",
                (nome, descricao, cap, id_lab),
            )
            if cur.rowcount == 0:
                return False, "Laboratório não encontrado."
            registrar_log_admin(
                conn, executor_id, executor_nome, "EDITAR_LAB", f"Laboratório ID {id_lab} atualizado para '{nome}'."
            )
        return True, "Laboratório atualizado com sucesso."
    except sqlite3.IntegrityError:
        return False, "Já existe outro laboratório com este nome."
    finally:
        conn.close()


def ExcluirLaboratorio(
    id_lab: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str]:
    conn = get_db(db_path)
    try:
        with conn:
            lab = conn.execute("SELECT nome FROM Laboratorio WHERE id = ?", (id_lab,)).fetchone()
            if not lab:
                return False, "Laboratório não encontrado."
            conn.execute("DELETE FROM Reserva WHERE id_laboratorio = ?", (id_lab,))
            conn.execute("DELETE FROM Laboratorio WHERE id = ?", (id_lab,))
            registrar_log_admin(
                conn, executor_id, executor_nome, "EXCLUIR_LAB", f"Laboratório '{lab['nome']}' excluído."
            )
        return True, "Laboratório excluído com sucesso."
    finally:
        conn.close()


# ---------- VALIDACAO DE DATAS E RESERVAS ----------

def validar_data_iso(data_str: str) -> date | None:
    if not data_str or not isinstance(data_str, str):
        return None
    try:
        return date.fromisoformat(data_str.strip())
    except ValueError:
        return None


def ReservarLaboratorio(
    id_usuario: int,
    id_lab: int,
    data_str: str,
    periodo: int,
    descricao: str = "",
    momento_ref: datetime | None = None,
    db_path: str | None = None,
) -> tuple[bool, str]:
    """
    Cria uma reserva simples com bloqueio transacional BEGIN IMMEDIATE,
    garantindo exclusividade mesmo sob requisicoes simultaneas.
    """
    agora = momento_ref or agora_campus()
    hoje_campus = agora.date()

    data_obj = validar_data_iso(data_str)
    if not data_obj:
        return False, "msg_data_invalida"

    if not isinstance(periodo, int) or periodo not in PERIODOS:
        return False, "msg_periodo_invalido"

    if data_obj < hoje_campus:
        return False, "msg_data_passada"

    if data_obj == hoje_campus and periodo_ja_comecou_hoje(periodo, agora):
        return False, "msg_periodo_iniciado"

    descricao_limpa = (descricao or "").strip()[:200]
    data_iso = data_obj.isoformat()

    conn = get_db(db_path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")

        lab = conn.execute("SELECT id FROM Laboratorio WHERE id = ?", (id_lab,)).fetchone()
        if not lab:
            conn.execute("ROLLBACK")
            return False, "msg_lab_invalido"

        usr = conn.execute("SELECT id FROM SistemaUsuario WHERE id = ?", (id_usuario,)).fetchone()
        if not usr:
            conn.execute("ROLLBACK")
            return False, "msg_acesso_negado"

        ocupado = conn.execute(
            "SELECT 1 FROM Reserva WHERE id_laboratorio = ? AND data_reserva = ? AND periodo = ?",
            (id_lab, data_iso, periodo),
        ).fetchone()
        if ocupado:
            conn.execute("ROLLBACK")
            return False, "msg_reserva_conflito"

        conn.execute(
            "INSERT INTO Reserva (id_usuario, id_laboratorio, data_reserva, periodo, descricao, serie_id) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (id_usuario, id_lab, data_iso, periodo, descricao_limpa),
        )
        conn.execute("COMMIT")
        return True, "msg_reserva_sucesso"
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return False, "msg_reserva_conflito"
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------- RESERVAS RECORRENTES ----------

def gerar_datas_recorrentes(
    data_inicio_str: str,
    data_fim_str: str,
    dia_semana: int,
    periodo: int,
    momento_ref: datetime | None = None,
) -> tuple[bool, str | list[str]]:
    """
    Calcula todas as datas correspondentes ao dia_semana (0=Segunda .. 6=Domingo)
    dentro do intervalo [data_inicio, data_fim], validando datas passadas ou periodos iniciados.
    """
    agora = momento_ref or agora_campus()
    hoje_campus = agora.date()

    dt_ini = validar_data_iso(data_inicio_str)
    dt_fim = validar_data_iso(data_fim_str)
    if not dt_ini or not dt_fim:
        return False, "msg_data_invalida"
    if not isinstance(dia_semana, int) or dia_semana < 0 or dia_semana > 6:
        return False, "msg_data_invalida"
    if not isinstance(periodo, int) or periodo not in PERIODOS:
        return False, "msg_periodo_invalido"
    if dt_ini < hoje_campus:
        return False, "msg_data_passada"
    if dt_fim < dt_ini:
        return False, "msg_intervalo_datas_invalido"
    if (dt_fim - dt_ini).days > 180:
        return False, "msg_intervalo_muito_longo"

    datas = []
    atual = dt_ini
    while atual <= dt_fim:
        if atual.weekday() == dia_semana:
            if atual == hoje_campus and periodo_ja_comecou_hoje(periodo, agora):
                pass
            else:
                datas.append(atual.isoformat())
        atual += timedelta(days=1)

    if not datas:
        return False, "msg_nenhuma_data_dia_semana"

    return True, datas


def verificar_conflitos_recorrencia(
    id_lab: int,
    data_inicio_str: str,
    data_fim_str: str,
    dia_semana: int,
    periodo: int,
    momento_ref: datetime | None = None,
    db_path: str | None = None,
) -> tuple[bool, str | dict]:
    """
    Analisa todas as ocorrencias de uma reserva recorrente e separa
    as datas disponiveis das datas conflitantes com detalhes do responsavel.
    """
    lab = BuscarLaboratorio(id_lab, db_path=db_path)
    if not lab:
        return False, "msg_lab_invalido"

    ok, resultado = gerar_datas_recorrentes(
        data_inicio_str, data_fim_str, dia_semana, periodo, momento_ref=momento_ref
    )
    if not ok:
        return False, resultado  # chave de erro

    datas_candidatas: list[str] = resultado  # type: ignore
    conn = get_db(db_path)
    try:
        placeholders = ",".join("?" for _ in datas_candidatas)
        rows = conn.execute(
            f"""
            SELECT r.data_reserva, u.nome AS responsavel, r.descricao
            FROM Reserva r
            JOIN SistemaUsuario u ON u.id = r.id_usuario
            WHERE r.id_laboratorio = ? AND r.periodo = ? AND r.data_reserva IN ({placeholders})
            """,
            [id_lab, periodo, *datas_candidatas],
        ).fetchall()

        mapa_conflitos = {
            row["data_reserva"]: {
                "data": row["data_reserva"],
                "responsavel": row["responsavel"],
                "descricao": row["descricao"] or "",
            }
            for row in rows
        }

        disponiveis = [d for d in datas_candidatas if d not in mapa_conflitos]
        conflitantes = [mapa_conflitos[d] for d in datas_candidatas if d in mapa_conflitos]

        return True, {
            "laboratorio_id": id_lab,
            "laboratorio_nome": lab["nome"],
            "dia_semana": dia_semana,
            "data_inicio": data_inicio_str,
            "data_fim": data_fim_str,
            "periodo": periodo,
            "disponiveis": disponiveis,
            "conflitantes": conflitantes,
        }
    finally:
        conn.close()


def confirmar_reserva_recorrente(
    id_usuario: int,
    id_lab: int,
    data_inicio_str: str,
    data_fim_str: str,
    dia_semana: int,
    periodo: int,
    descricao: str = "",
    modo: str = "apenas_disponiveis",
    momento_ref: datetime | None = None,
    db_path: str | None = None,
) -> tuple[bool, str, dict]:
    """
    Executa transacionalmente a criacao da serie recorrente.
    - modo == 'exigir_todas': aborta se houver qualquer conflito.
    - modo == 'apenas_disponiveis': reserva apenas as datas livres, ignorando conflitos.
    """
    ok, analise = verificar_conflitos_recorrencia(
        id_lab, data_inicio_str, data_fim_str, dia_semana, periodo, momento_ref=momento_ref, db_path=db_path
    )
    if not ok:
        return False, analise, {}  # type: ignore

    descricao_limpa = (descricao or "").strip()[:200]
    serie_id = uuid.uuid4().hex[:16]

    conn = get_db(db_path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")

        # Revalida conflitos dentro da transacao exclusiva
        datas_alvo = analise["disponiveis"] + [c["data"] for c in analise["conflitantes"]]  # type: ignore
        placeholders = ",".join("?" for _ in datas_alvo)
        ocupadas_agora = {
            row["data_reserva"]
            for row in conn.execute(
                f"SELECT data_reserva FROM Reserva WHERE id_laboratorio = ? AND periodo = ? AND data_reserva IN ({placeholders})",
                [id_lab, periodo, *datas_alvo],
            ).fetchall()
        }

        if modo == "exigir_todas" and ocupadas_agora:
            conn.execute("ROLLBACK")
            return False, "msg_reserva_conflito", {"conflitos": sorted(ocupadas_agora)}

        livres_finais = [d for d in sorted(datas_alvo) if d not in ocupadas_agora]
        if not livres_finais:
            conn.execute("ROLLBACK")
            return False, "msg_sem_datas_livres", {}

        for data_iso in livres_finais:
            conn.execute(
                "INSERT INTO Reserva (id_usuario, id_laboratorio, data_reserva, periodo, descricao, serie_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id_usuario, id_lab, data_iso, periodo, descricao_limpa, serie_id),
            )

        conn.execute("COMMIT")
        return True, "msg_serie_criada", {"qtd": len(livres_finais), "serie_id": serie_id}
    except sqlite3.IntegrityError:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return False, "msg_reserva_conflito", {}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ---------- CONSULTAS DE DISPONIBILIDADE E RESPONSAVEIS ----------

def DisponibilidadeDetalhadaNaData(data_str: str, db_path: str | None = None) -> dict:
    """
    Retorna a grade detalhada {id_lab: {periodo: info_dict | None}} para a data.
    Quando ocupado, inclui id_reserva, id_usuario, responsavel_nome, responsavel_email, descricao e serie_id.
    """
    labs = ListarLaboratorios(db_path=db_path)
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT r.id AS id_reserva, r.id_laboratorio, r.periodo, r.descricao, r.serie_id,
                   u.id AS id_usuario, u.nome AS responsavel_nome, u.email AS responsavel_email
            FROM Reserva r
            JOIN SistemaUsuario u ON u.id = r.id_usuario
            WHERE r.data_reserva = ?
            """,
            (data_str,),
        ).fetchall()

        ocupados = {}
        for row in rows:
            ocupados.setdefault(row["id_laboratorio"], {})[row["periodo"]] = {
                "id_reserva": row["id_reserva"],
                "id_usuario": row["id_usuario"],
                "responsavel_nome": row["responsavel_nome"],
                "responsavel_email": row["responsavel_email"],
                "descricao": row["descricao"] or "",
                "serie_id": row["serie_id"],
            }

        grade = {}
        for lab in labs:
            id_lab = lab["id"]
            grade[id_lab] = {
                periodo: ocupados.get(id_lab, {}).get(periodo)
                for periodo in PERIODOS
            }
        return grade
    finally:
        conn.close()


def ListarReservasFuturasDoUsuario(id_usuario: int, db_path: str | None = None):
    hoje = agora_campus().date().isoformat()
    conn = get_db(db_path)
    try:
        return conn.execute(
            """
            SELECT r.id, r.data_reserva, r.periodo, r.descricao, l.nome AS lab_nome, r.serie_id
            FROM Reserva r
            JOIN Laboratorio l ON l.id = r.id_laboratorio
            WHERE r.id_usuario = ? AND r.data_reserva >= ?
            ORDER BY r.data_reserva ASC, r.periodo ASC
            """,
            (id_usuario, hoje),
        ).fetchall()
    finally:
        conn.close()


def ListarReservasPassadasDoUsuario(id_usuario: int, db_path: str | None = None):
    hoje = agora_campus().date().isoformat()
    conn = get_db(db_path)
    try:
        return conn.execute(
            """
            SELECT r.id, r.data_reserva, r.periodo, r.descricao, l.nome AS lab_nome, r.serie_id
            FROM Reserva r
            JOIN Laboratorio l ON l.id = r.id_laboratorio
            WHERE r.id_usuario = ? AND r.data_reserva < ?
            ORDER BY r.data_reserva DESC, r.periodo DESC
            """,
            (id_usuario, hoje),
        ).fetchall()
    finally:
        conn.close()


def ListarTodasReservas(db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            """
            SELECT r.id, r.data_reserva, r.periodo, r.descricao,
                   l.nome AS lab_nome, u.nome AS usuario_nome, u.email AS usuario_email,
                   u.codigo_barras AS usuario_codigo, r.serie_id
            FROM Reserva r
            JOIN Laboratorio l ON l.id = r.id_laboratorio
            JOIN SistemaUsuario u ON u.id = r.id_usuario
            ORDER BY r.data_reserva DESC, r.periodo ASC
            """
        ).fetchall()
    finally:
        conn.close()


def ExcluirReserva(
    id_reserva: int,
    id_usuario: int,
    eh_admin: bool = False,
    admin_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str]:
    """Cancela uma ocorrencia individual. Usuario comum so cancela a propria reserva."""
    conn = get_db(db_path)
    try:
        with conn:
            reserva = conn.execute(
                """
                SELECT r.id, r.id_usuario, r.data_reserva, r.periodo, l.nome AS lab_nome, u.nome AS usuario_nome
                FROM Reserva r
                JOIN Laboratorio l ON l.id = r.id_laboratorio
                JOIN SistemaUsuario u ON u.id = r.id_usuario
                WHERE r.id = ?
                """,
                (id_reserva,),
            ).fetchone()

            if not reserva:
                return False, "msg_reserva_nao_encontrada"

            if not eh_admin and reserva["id_usuario"] != id_usuario:
                return False, "msg_reserva_nao_encontrada"

            conn.execute("DELETE FROM Reserva WHERE id = ?", (id_reserva,))
            if eh_admin and reserva["id_usuario"] != id_usuario:
                registrar_log_admin(
                    conn,
                    id_usuario,
                    admin_nome,
                    "CANCELAR_RESERVA_TERCEIRO",
                    f"Cancelada reserva #{id_reserva} de {reserva['usuario_nome']} ({reserva['lab_nome']}, {reserva['data_reserva']}, P{reserva['periodo']}).",
                )
        return True, "msg_reserva_cancelada"
    finally:
        conn.close()


def ExcluirSerieReservas(
    serie_id: str,
    id_usuario: int,
    eh_admin: bool = False,
    admin_nome: str = "ADMIN",
    db_path: str | None = None,
) -> tuple[bool, str, int]:
    """Cancela todas as ocorrencias futuras (ou todas, se admin) de uma serie recorrente."""
    if not serie_id:
        return False, "msg_reserva_nao_encontrada", 0

    hoje = agora_campus().date().isoformat()
    conn = get_db(db_path)
    try:
        with conn:
            if eh_admin:
                cur = conn.execute(
                    "DELETE FROM Reserva WHERE serie_id = ? AND data_reserva >= ?",
                    (serie_id, hoje),
                )
                qtd = cur.rowcount
                if qtd > 0:
                    registrar_log_admin(
                        conn,
                        id_usuario,
                        admin_nome,
                        "CANCELAR_SERIE_RESERVAS",
                        f"Cancelada série '{serie_id}' ({qtd} reservas futuras).",
                    )
            else:
                cur = conn.execute(
                    "DELETE FROM Reserva WHERE serie_id = ? AND id_usuario = ? AND data_reserva >= ?",
                    (serie_id, id_usuario, hoje),
                )
                qtd = cur.rowcount

            if qtd == 0:
                return False, "msg_reserva_nao_encontrada", 0
        return True, "msg_serie_cancelada", qtd
    finally:
        conn.close()


# ---------- VALIDACAO TEMPORAL DE ACESSO FISICO (RASPBERRY PI) ----------

def validar_acesso_fisico_codigo(
    codigo_barras: str,
    id_laboratorio: int,
    momento: datetime | None = None,
    db_path: str | None = None,
) -> tuple[bool, str]:
    """
    Valida o acesso fisico por codigo de barras conforme a especificacao do projeto:
    1. Verifica se o codigo pertence a um usuario cadastrado.
    2. Administradores (admin / super_admin) possuem autorizacao permanente.
    3. Usuarios comuns precisam ter reserva valida para o laboratorio, data e periodo ativo.
       Durante o intervalo noturno (20:20-20:40), o acesso nao e liberado para reservas comuns.
    """
    codigo = (codigo_barras or "").strip()
    if not codigo:
        return False, "Código de barras vazio."

    ref = momento or agora_campus()
    conn = get_db(db_path)
    try:
        usuario = conn.execute(
            "SELECT id, nome, nivel_admin FROM SistemaUsuario WHERE codigo_barras = ?",
            (codigo,),
        ).fetchone()
        if not usuario:
            return False, f"Código '{codigo}' não cadastrado no sistema."

        if usuario["nivel_admin"] in ("admin", "super_admin"):
            return True, f"Acesso administrativo autorizado: {usuario['nome']}."

        periodo_atual = periodo_ativo_no_momento(ref)
        if periodo_atual is None:
            return False, f"Usuário {usuario['nome']} identificado, mas fora do horário de aula ou em intervalo."

        data_hoje = ref.date().isoformat()
        reserva = conn.execute(
            """
            SELECT r.id, l.nome AS lab_nome
            FROM Reserva r
            JOIN Laboratorio l ON l.id = r.id_laboratorio
            WHERE r.id_usuario = ? AND r.id_laboratorio = ? AND r.data_reserva = ? AND r.periodo = ?
            """,
            (usuario["id"], id_laboratorio, data_hoje, periodo_atual),
        ).fetchone()

        if reserva:
            return True, (
                f"Acesso liberado para {usuario['nome']} no {reserva['lab_nome']} "
                f"(Período {periodo_atual}: {PERIODOS[periodo_atual]})."
            )

        return False, (
            f"Usuário {usuario['nome']} sem reserva válida para este laboratório "
            f"no Período {periodo_atual} ({PERIODOS[periodo_atual]})."
        )
    finally:
        conn.close()


def Periodos():
    return PERIODOS