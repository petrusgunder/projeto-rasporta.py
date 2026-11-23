import os
import shutil
import sqlite3
from config_sistema import agora_campus, obter_diretorio_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = obter_diretorio_dados(BASE_DIR)
DB_PATH = os.environ.get("RASPORTA_DB_PATH", os.path.join(DATA_DIR, "banco.db"))
BACKUP_DIR = os.environ.get("RASPORTA_BACKUP_DIR", os.path.join(DATA_DIR, "backups"))


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    """
    Abre uma conexao SQLite isolada por thread/requisicao, com:
    - Chaves estrangeiras ativadas (PRAGMA foreign_keys = ON)
    - Timeout de concorrencia (5000 ms)
    - Modo WAL para leituras/escritas concorrentes seguras
    """
    caminho = db_path or DB_PATH
    pasta_pai = os.path.dirname(os.path.abspath(caminho))
    if pasta_pai:
        os.makedirs(pasta_pai, exist_ok=True)

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

    if not os.path.exists(origem_path):
        return ""

    timestamp = agora_campus().strftime("%Y%m%d_%H%M%S_%f")
    arquivo_backup = os.path.join(pasta_destino, f"banco_backup_{timestamp}.db")

    src = sqlite3.connect(origem_path, timeout=10.0)
    dst = sqlite3.connect(arquivo_backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    try:
        os.chmod(arquivo_backup, 0o600)
    except OSError:
        pass

    # Mantem no maximo os 30 backups mais recentes
    arquivos = sorted(
        [
            os.path.join(pasta_destino, f)
            for f in os.listdir(pasta_destino)
            if f.startswith("banco_backup_") and f.endswith(".db")
        ]
    )
    for antigo in arquivos[:-30]:
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
    # Remove arquivos WAL/SHM residuais antes de sobrescrever
    for sufixo in ("-wal", "-shm"):
        if os.path.exists(destino_path + sufixo):
            os.remove(destino_path + sufixo)
    shutil.copy2(arquivo_backup, destino_path)


def inicializar_banco(db_path: str | None = None) -> None:
    """
    Cria tabelas, indices e aplica migracoes seguras sem apagar dados existentes.
    """
    caminho = db_path or DB_PATH
    if os.path.exists(caminho) and os.environ.get("RASPORTA_BACKUP_ON_BOOT", "1") == "1":
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

                CREATE TABLE IF NOT EXISTS EstacaoLeitura (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    identificador VARCHAR(64) NOT NULL UNIQUE,
                    nome VARCHAR(100) NOT NULL,
                    id_laboratorio INTEGER NOT NULL,
                    segredo_hmac VARCHAR(128) NOT NULL,
                    ativa INTEGER NOT NULL DEFAULT 1,
                    ultimo_contato TIMESTAMP,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (id_laboratorio) REFERENCES Laboratorio(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS LogVerificacaoFisica (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    estacao_identificador VARCHAR(64) NOT NULL,
                    id_laboratorio INTEGER NOT NULL,
                    codigo_mascarado VARCHAR(32) NOT NULL,
                    usuario_id INTEGER,
                    autorizado INTEGER NOT NULL,
                    motivo VARCHAR(200) NOT NULL,
                    ip_origem VARCHAR(64),
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_verificacao_criado ON LogVerificacaoFisica(criado_em DESC)"
            )
    finally:
        conn.close()


inicializar_banco()