#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="/opt/rasporta/dados_persistentes"
DB_FILE="${DATA_DIR}/banco.db"
BACKUP_DIR="${DATA_DIR}/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST_FILE="${BACKUP_DIR}/banco_backup_${TIMESTAMP}.db"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

if [ ! -f "${DB_FILE}" ]; then
    echo "Banco de dados nao encontrado em ${DB_FILE}."
    exit 0
fi

# Backup transacional a quente via API nativa do SQLite
sqlite3 "${DB_FILE}" ".backup '${DEST_FILE}'"
chmod 600 "${DEST_FILE}"

# Verifica integridade do backup gerado
INTEGRIDADE="$(sqlite3 "${DEST_FILE}" "PRAGMA integrity_check;")"
if [ "${INTEGRIDADE}" != "ok" ]; then
    echo "ERRO: Falha na verificacao de integridade do backup ${DEST_FILE}" >&2
    rm -f "${DEST_FILE}"
    exit 1
fi

# Mantem os 30 backups mais recentes
ls -1t "${BACKUP_DIR}"/banco_backup_*.db 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "Backup concluido e verificado com sucesso: ${DEST_FILE}"