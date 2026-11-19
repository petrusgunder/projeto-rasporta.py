import os
import shutil
import sqlite3
from datetime import datetime
from config_sistema import PERIODOS, agora_campus

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RASPORTA_DB_PATH", os.path.join(BASE_DIR, "banco.db"))
BACKUP_DIR = os.path.join(BASE_DIR, "backups")


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """
    Abre uma conexao SQLite isolada por thread/requisicao, com:
    - Chaves estrangeiras ativadas (PRAGMA foreign_keys = ON)
    - Timeout de concorrencia (5000 ms)
    - Modo WAL para leituras/escritas concorrentes seguras
    """
    caminho = db_path or DB_PATH
    conn = sqlite3.connect(caminho, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    except sqlite3.OperationalError:
        pass
    return conn


def _coluna_existe(conn: sqlite3.Connection, tabela: str, coluna: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({tabela})")
    return any(row[1] == coluna for row in cur.fetchall())


def criar_backup_banco(db_path: str | None = None, destino_dir: str | None = None) -> str:
    """
    Realiza copia consistente a quente do SQLite usando a API nativa sqlite3.backup().
    Retorna o caminho do arquivo de backup gerado.
    """
    origem_path = db_path or DB_PATH
    pasta_destino = destino_dir or BACKUP_DIR
    os.makedirs(pasta_destino, exist_ok=True)

    timestamp = agora_campus().strftime("%Y%m%d_%H%M%S")
    arquivo_backup = os.path.join(pasta_destino, f"banco_backup_{timestamp}.db")

    if not os.path.exists(origem_path):
        return ""

    src = sqlite3.connect(origem_path)
    dst = sqlite3.connect(arquivo_backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Mantem no maximo os 15 backups mais recentes
    arquivos = sorted(
        [
            os.path.join(pasta_destino, f)
            for f in os.listdir(pasta_destino)
            if f.startswith("banco_backup_") and f.endswith(".db")
        ]
    )
    for antigo in arquivos[:-15]:
        try:
            os.remove(antigo)
        except OSError:
            pass

    return arquivo_backup


def restaurar_backup_banco(arquivo_backup: str, db_path: str | None = None) -> None:
    """Restaura um arquivo de backup SQLite de forma segura."""
    destino_path = db_path or DB_PATH
    if not os.path.exists(arquivo_backup):
        raise FileNotFoundError(f"Backup nao encontrado: {arquivo_backup}")
    criar_backup_banco(destino_path)
    shutil.copy2(arquivo_backup, destino_path)


def inicializar_banco(db_path: str | None = None) -> None:
    """
    Cria tabelas, indices e aplica migracoes seguras sem apagar dados existentes.
    """
    caminho = db_path or DB_PATH
    if os.path.exists(caminho):
        criar_backup_banco(caminho)

    conn = get_db(caminho)
    try:
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS Usuario(
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(50) NOT NULL,
                    cargo VARCHAR(10) NOT NULL,
                    email VARCHAR(50) NOT NULL
                );

                CREATE TABLE IF NOT EXISTS Digital(
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    codigo VARCHAR(10) NOT NULL
                );

                CREATE TABLE IF NOT EXISTS UsuarioDigital(
                    id_usuario INTEGER NOT NULL,
                    id_digital INTEGER NOT NULL,
                    FOREIGN KEY (id_usuario) REFERENCES Usuario(id) ON DELETE CASCADE,
                    FOREIGN KEY (id_digital) REFERENCES Digital(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS SistemaUsuario (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(100) NOT NULL,
                    email VARCHAR(100) NOT NULL UNIQUE,
                    senha_hash VARCHAR(200) NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    nivel_admin VARCHAR(20) NOT NULL DEFAULT 'usuario',
                    codigo_barras VARCHAR(50),
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS Laboratorio (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(50) NOT NULL UNIQUE,
                    descricao VARCHAR(200),
                    capacidade INTEGER NOT NULL DEFAULT 30
                );

                CREATE TABLE IF NOT EXISTS Reserva (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    id_usuario INTEGER NOT NULL,
                    id_laboratorio INTEGER NOT NULL,
                    data_reserva DATE NOT NULL,
                    periodo INTEGER NOT NULL,
                    descricao VARCHAR(200),
                    serie_id VARCHAR(64),
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (id_usuario) REFERENCES SistemaUsuario(id) ON DELETE CASCADE,
                    FOREIGN KEY (id_laboratorio) REFERENCES Laboratorio(id) ON DELETE CASCADE,
                    UNIQUE(id_laboratorio, data_reserva, periodo)
                );

                CREATE TABLE IF NOT EXISTS LogAdmin (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    admin_nome VARCHAR(100) NOT NULL,
                    acao VARCHAR(80) NOT NULL,
                    detalhes TEXT NOT NULL,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Migracoes seguras para bancos pre-existentes
            if not _coluna_existe(conn, "SistemaUsuario", "codigo_barras"):
                conn.execute("ALTER TABLE SistemaUsuario ADD COLUMN codigo_barras VARCHAR(50)")

            if not _coluna_existe(conn, "SistemaUsuario", "nivel_admin"):
                conn.execute(
                    "ALTER TABLE SistemaUsuario ADD COLUMN nivel_admin VARCHAR(20) NOT NULL DEFAULT 'usuario'"
                )
                # Preserva administradores existentes promovendo o primeiro a super_admin
                admins = conn.execute(
                    "SELECT id FROM SistemaUsuario WHERE is_admin = 1 ORDER BY id ASC"
                ).fetchall()
                for idx, row in enumerate(admins):
                    nivel = "super_admin" if idx == 0 else "admin"
                    conn.execute(
                        "UPDATE SistemaUsuario SET nivel_admin = ? WHERE id = ?",
                        (nivel, row["id"]),
                    )

            if not _coluna_existe(conn, "Reserva", "serie_id"):
                conn.execute("ALTER TABLE Reserva ADD COLUMN serie_id VARCHAR(64)")

            # Indices de integridade e desempenho
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuario_codigo_barras "
                "ON SistemaUsuario(codigo_barras) WHERE codigo_barras IS NOT NULL AND codigo_barras != ''"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reserva_data_lab ON Reserva(data_reserva, id_laboratorio)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reserva_usuario ON Reserva(id_usuario, data_reserva)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reserva_serie ON Reserva(serie_id)"
            )
    finally:
        conn.close()


inicializar_banco()