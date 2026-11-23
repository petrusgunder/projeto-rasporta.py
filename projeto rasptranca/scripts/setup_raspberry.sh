#!/usr/bin/env bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Execute este script com sudo: sudo bash scripts/setup_raspberry.sh"
    exit 1
fi

APP_DIR="/opt/rasporta"
ETC_DIR="/etc/rasporta"

echo "=== 1. Atualizando sistema operacional ==="
apt-get update && apt-get upgrade -y

echo "=== 2. Instalando pacotes essenciais, Docker, SQLite e GPIO ==="
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    sqlite3 \
    ufw \
    python3 \
    python3-venv \
    python3-pip \
    python3-lgpio \
    python3-gpiozero

if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi

systemctl enable --now docker

echo "=== 3. Criando usuario de servico 'rasporta' com acesso a Docker, GPIO e Input ==="
if ! id -u rasporta >/dev/null 2>&1; then
    useradd --system --create-home --shell /bin/bash rasporta
fi
usermod -aG docker,gpio,input rasporta || usermod -aG docker,input rasporta

echo "=== 4. Preparando diretorios de aplicacao e dados persistentes ==="
mkdir -p "${APP_DIR}/dados_persistentes/backups" "${ETC_DIR}"
cp -r . "${APP_DIR}/"
chown -R 1000:1000 "${APP_DIR}/dados_persistentes"
chmod 700 "${APP_DIR}/dados_persistentes"

echo "=== 5. Criando ambiente virtual isolado do verificador fisico ==="
python3 -m venv --system-site-packages "${APP_DIR}/.venv-verificador"
"${APP_DIR}/.venv-verificador/bin/pip" install --upgrade pip
"${APP_DIR}/.venv-verificador/bin/pip" install requests==2.32.3

if [ ! -f "${ETC_DIR}/estacao.env" ]; then
    cat > "${ETC_DIR}/estacao.env" <<'EOF'
RASPORTA_API_URL=http://127.0.0.1:5000
RASPORTA_STATION_ID=estacao-lab-info-1
RASPORTA_STATION_SECRET=PREENCHA_COM_O_SEGREDO_GERADO_NO_PAINEL_ADMIN
RASPORTA_API_TIMEOUT=4.0
RASPORTA_GPIO_VERDE=17
RASPORTA_GPIO_VERMELHO=27
# Descomente e ajuste para leitor USB HID dedicado sem terminal ativo:
# RASPORTA_HID_DEVICE=/dev/input/by-id/usb-LEITOR_CODIGO_BARRAS-event-kbd
EOF
    chmod 600 "${ETC_DIR}/estacao.env"
    chown rasporta:rasporta "${ETC_DIR}/estacao.env"
fi

echo "=== 6. Registrando servicos systemd (Verificador + Backups) ==="
chmod +x "${APP_DIR}/scripts/backup_banco.sh"
cp "${APP_DIR}/systemd/rasporta-verificador.service" /etc/systemd/system/
cp "${APP_DIR}/systemd/rasporta-backup.service" /etc/systemd/system/
cp "${APP_DIR}/systemd/rasporta-backup.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable rasporta-verificador.service
systemctl enable --now rasporta-backup.timer

echo "=== 7. Configurando Firewall UFW ==="
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
# Libere 80/443 apenas se usar Caddy/DuckDNS com port-forwarding:
# ufw allow 80/tcp
# ufw allow 443/tcp
ufw --force enable

echo "=== Provisionamento concluido! ==="