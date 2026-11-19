"""
CRUD e controle de permissoes dos usuarios do Sistema de Agenda.
Sem senhas administrativas fixas no codigo-fonte.
"""
import os
import re
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from banco_de_dados import get_db

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NIVEIS_VALIDOS = ("usuario", "admin", "super_admin")


def registrar_log_admin(conn: sqlite3.Connection, admin_id: int | None, admin_nome: str, acao: str, detalhes: str) -> None:
    conn.execute(
        "INSERT INTO LogAdmin (admin_id, admin_nome, acao, detalhes) VALUES (?, ?, ?, ?)",
        (admin_id, admin_nome, acao, detalhes),
    )


def listar_logs_admin(limite: int = 100, db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, admin_id, admin_nome, acao, detalhes, criado_em "
            "FROM LogAdmin ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    finally:
        conn.close()


def existe_super_admin(db_path: str | None = None) -> bool:
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM SistemaUsuario WHERE nivel_admin = 'super_admin' LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def inicializar_admin_via_ambiente(db_path: str | None = None) -> bool:
    """
    Cria o primeiro Administrador Principal caso ainda nao exista nenhum,
    utilizando exclusivamente variaveis de ambiente:
      - RASPORTA_ADMIN_NOME (opcional, padrao: 'Administrador Principal')
      - RASPORTA_ADMIN_EMAIL
      - RASPORTA_ADMIN_SENHA
    Nao cria credenciais padrao previsiveis.
    """
    if existe_super_admin(db_path):
        return False

    email = (os.environ.get("RASPORTA_ADMIN_EMAIL") or "").strip().lower()
    senha = os.environ.get("RASPORTA_ADMIN_SENHA") or ""
    nome = (os.environ.get("RASPORTA_ADMIN_NOME") or "Administrador Principal").strip()

    if not email or not senha or len(senha) < 8:
        return False

    ok, _ = CadastrarUsuarioSistema(
        nome=nome,
        email=email,
        senha=senha,
        nivel_admin="super_admin",
        db_path=db_path,
        executor_nome="BOOTSTRAP_ENV",
    )
    return ok


def CadastrarUsuarioSistema(
    nome: str,
    email: str,
    senha: str,
    nivel_admin: str = "usuario",
    codigo_barras: str | None = None,
    db_path: str | None = None,
    executor_id: int | None = None,
    executor_nome: str = "SISTEMA",
) -> tuple[bool, str]:
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    codigo_barras = (codigo_barras or "").strip() or None

    if not nome or len(nome) < 2:
        return False, "Informe um nome válido (mínimo 2 caracteres)."
    if not email or not EMAIL_REGEX.match(email):
        return False, "E-mail inválido."
    if not senha or len(senha) < 8:
        return False, "A senha deve ter pelo menos 8 caracteres."
    if nivel_admin not in NIVEIS_VALIDOS:
        nivel_admin = "usuario"

    is_admin_flag = 1 if nivel_admin in ("admin", "super_admin") else 0
    hash_senha = generate_password_hash(senha)

    conn = get_db(db_path)
    try:
        with conn:
            existente = conn.execute(
                "SELECT 1 FROM SistemaUsuario WHERE email = ?", (email,)
            ).fetchone()
            if existente:
                return False, "Já existe um usuário cadastrado com este e-mail."

            if codigo_barras:
                cod_existente = conn.execute(
                    "SELECT 1 FROM SistemaUsuario WHERE codigo_barras = ?", (codigo_barras,)
                ).fetchone()
                if cod_existente:
                    return False, "Este código de barras já está vinculado a outro usuário."

            conn.execute(
                "INSERT INTO SistemaUsuario (nome, email, senha_hash, is_admin, nivel_admin, codigo_barras) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (nome, email, hash_senha, is_admin_flag, nivel_admin, codigo_barras),
            )
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "CADASTRAR_USUARIO",
                f"Usuário '{nome}' ({email}) criado com nível '{nivel_admin}'.",
            )
        return True, "Usuário cadastrado com sucesso!"
    except sqlite3.IntegrityError:
        return False, "Conflito de unicidade (e-mail ou código de barras já cadastrado)."
    finally:
        conn.close()


def AutenticarUsuario(email: str, senha: str, db_path: str | None = None):
    email = (email or "").strip().lower()
    if not email or not senha:
        return None
    conn = get_db(db_path)
    try:
        usuario = conn.execute(
            "SELECT id, nome, email, senha_hash, is_admin, nivel_admin, codigo_barras "
            "FROM SistemaUsuario WHERE email = ?",
            (email,),
        ).fetchone()
        if usuario and check_password_hash(usuario["senha_hash"], senha):
            return usuario
        return None
    finally:
        conn.close()


def BuscarUsuarioSistema(id_usuario: int, db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, nome, email, is_admin, codigo_barras, nivel_admin "
            "FROM SistemaUsuario WHERE id = ?",
            (id_usuario,),
        ).fetchone()
    finally:
        conn.close()


def ListarUsuariosSistema(db_path: str | None = None):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, nome, email, is_admin, codigo_barras, nivel_admin "
            "FROM SistemaUsuario ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()


def EditarUsuarioSistema(
    id_usuario: int,
    nome: str,
    email: str,
    nivel_admin_desejado: str,
    codigo_barras: str | None = None,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    executor_nivel: str = "admin",
    db_path: str | None = None,
) -> tuple[bool, str]:
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    codigo_barras = (codigo_barras or "").strip() or None

    if not nome or not email or not EMAIL_REGEX.match(email):
        return False, "Nome ou e-mail inválidos."
    if nivel_admin_desejado not in NIVEIS_VALIDOS:
        return False, "Nível de permissão inválido."

    conn = get_db(db_path)
    try:
        with conn:
            alvo = conn.execute(
                "SELECT id, nome, email, nivel_admin FROM SistemaUsuario WHERE id = ?",
                (id_usuario,),
            ).fetchone()
            if not alvo:
                return False, "Usuário não encontrado."

            nivel_atual = alvo["nivel_admin"]

            # Apenas super_admin pode alterar niveis administrativos ou editar outro administrador
            if executor_nivel != "super_admin":
                if nivel_atual in ("admin", "super_admin") or nivel_admin_desejado != nivel_atual:
                    return False, "Apenas um Administrador Principal pode gerenciar privilégios administrativos."

            # Impede remover/rebaixar o ultimo super_admin
            if nivel_atual == "super_admin" and nivel_admin_desejado != "super_admin":
                qtd_super = conn.execute(
                    "SELECT COUNT(*) FROM SistemaUsuario WHERE nivel_admin = 'super_admin'"
                ).fetchone()[0]
                if qtd_super <= 1:
                    return False, "Operação bloqueada: não é permitido remover o último Administrador Principal."

            is_admin_flag = 1 if nivel_admin_desejado in ("admin", "super_admin") else 0
            conn.execute(
                "UPDATE SistemaUsuario SET nome = ?, email = ?, is_admin = ?, nivel_admin = ?, codigo_barras = ? "
                "WHERE id = ?",
                (nome, email, is_admin_flag, nivel_admin_desejado, codigo_barras, id_usuario),
            )
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "EDITAR_USUARIO",
                f"Usuário ID {id_usuario} ({email}) atualizado; nível: '{nivel_atual}' -> '{nivel_admin_desejado}'.",
            )
        return True, "Usuário atualizado com sucesso."
    except sqlite3.IntegrityError:
        return False, "E-mail ou código de barras já pertence a outro usuário."
    finally:
        conn.close()


def ExcluirUsuarioSistema(
    id_usuario: int,
    executor_id: int | None = None,
    executor_nome: str = "ADMIN",
    executor_nivel: str = "admin",
    db_path: str | None = None,
) -> tuple[bool, str]:
    conn = get_db(db_path)
    try:
        with conn:
            alvo = conn.execute(
                "SELECT id, nome, email, nivel_admin FROM SistemaUsuario WHERE id = ?",
                (id_usuario,),
            ).fetchone()
            if not alvo:
                return False, "Usuário não encontrado."

            if alvo["id"] == executor_id:
                return False, "Você não pode excluir sua própria conta enquanto está conectado."

            if alvo["nivel_admin"] in ("admin", "super_admin") and executor_nivel != "super_admin":
                return False, "Apenas um Administrador Principal pode excluir contas administrativas."

            if alvo["nivel_admin"] == "super_admin":
                qtd_super = conn.execute(
                    "SELECT COUNT(*) FROM SistemaUsuario WHERE nivel_admin = 'super_admin'"
                ).fetchone()[0]
                if qtd_super <= 1:
                    return False, "Operação bloqueada: não é possível excluir o último Administrador Principal."

            conn.execute("DELETE FROM Reserva WHERE id_usuario = ?", (id_usuario,))
            conn.execute("DELETE FROM SistemaUsuario WHERE id = ?", (id_usuario,))
            registrar_log_admin(
                conn,
                executor_id,
                executor_nome,
                "EXCLUIR_USUARIO",
                f"Usuário '{alvo['nome']}' ({alvo['email']}) excluído.",
            )
        return True, "Usuário excluído com sucesso."
    finally:
        conn.close()


def AlterarSenha(id_usuario: int, nova_senha: str, db_path: str | None = None) -> tuple[bool, str]:
    if not nova_senha or len(nova_senha) < 8:
        return False, "A nova senha deve ter pelo menos 8 caracteres."
    hash_senha = generate_password_hash(nova_senha)
    conn = get_db(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE SistemaUsuario SET senha_hash = ? WHERE id = ?", (hash_senha, id_usuario)
            )
        return True, "Senha atualizada com sucesso."
    finally:
        conn.close()


def BuscarUsuarioPorCodigoBarras(codigo: str, db_path: str | None = None):
    if not codigo:
        return None
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT id, nome, email, is_admin, codigo_barras, nivel_admin "
            "FROM SistemaUsuario WHERE codigo_barras = ?",
            (codigo.strip(),),
        ).fetchone()
    finally:
        conn.close()