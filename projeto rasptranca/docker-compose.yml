services:
  rasporta-web:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: rasporta-web
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - RASPORTA_DATA_DIR=/data
      - RASPORTA_DB_PATH=/data/banco.db
      - RASPORTA_BACKUP_DIR=/data/backups
    ports:
      # Expoe apenas em localhost (127.0.0.1) para que o proxy HTTPS (Caddy ou Cloudflare Tunnel)
      # controle todo o trafego externo e o verificador local tambem possa acessar se necessario.
      - "127.0.0.1:5000:5000"
    volumes:
      - ./dados_persistentes:/data
    security_opt:
      - no-new-privileges:true
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:5000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  # Proxy Reverso HTTPS automatico (Ativar com: docker compose --profile caddy up -d)
  caddy:
    image: caddy:2-alpine
    container_name: rasporta-caddy
    profiles: ["caddy"]
    restart: unless-stopped
    depends_on:
      rasporta-web:
        condition: service_healthy
    ports:
      - "80:80"
      - "443:443"
    environment:
      - RASPORTA_DOMINIO=${RASPORTA_DOMINIO}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  caddy_data:
  caddy_config: