"""
Servico Independente de Verificacao Fisica por Codigo de Barras (Raspberry Pi).
- Comunica-se exclusivamente via API REST autenticada por HMAC-SHA256.
- Nao acessa o banco SQLite diretamente.
- Fail-closed: qualquer falha de rede ou erro HTTP acende o LED vermelho.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rpi_luz import AcenderLuz, sinalizar_erro_rede

logging.basicConfig(
    level=os.environ.get("RASPORTA_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rasporta.verificador")

# Mapa basico de keycodes Linux evdev para leitores USB HID dedicados (/dev/input/event*)
EVDEV_KEYMAP = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "-", 16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u", 23: "i",
    24: "o", 25: "p", 30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j",
    37: "k", 38: "l", 44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m",
    52: ".", 53: "/",
}


def carregar_config_estacao() -> dict:
    api_base = (os.environ.get("RASPORTA_API_URL") or "").strip().rstrip("/")
    station_id = (os.environ.get("RASPORTA_STATION_ID") or "").strip()
    station_secret = (os.environ.get("RASPORTA_STATION_SECRET") or "").strip()
    timeout = float(os.environ.get("RASPORTA_API_TIMEOUT", "4.0"))
    hid_device = (os.environ.get("RASPORTA_HID_DEVICE") or "").strip()
    verify_ssl = os.environ.get("RASPORTA_VERIFY_SSL", "1") != "0"

    if not api_base or not station_id or not station_secret:
        logger.critical(
            "Variaveis obrigatorias ausentes: RASPORTA_API_URL, RASPORTA_STATION_ID, RASPORTA_STATION_SECRET."
        )
        sys.exit(2)

    return {
        "api_base": api_base,
        "endpoint_verificar": f"{api_base}/api/v1/estacoes/verificar",
        "endpoint_health": f"{api_base}/health",
        "station_id": station_id,
        "station_secret": station_secret,
        "timeout": timeout,
        "hid_device": hid_device,
        "verify_ssl": verify_ssl,
    }


def criar_sessao_http() -> requests.Session:
    sessao = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=0.2,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    sessao.mount("https://", adapter)
    sessao.mount("http://", adapter)
    return sessao


def consultar_autorizacao_api(sessao: requests.Session, cfg: dict, codigo_barras: str) -> tuple[bool, str, bool]:
    """
    Envia requisicao autenticada para o servidor Rasporta.
    Retorna (autorizado, mensagem, erro_de_rede).
    """
    payload_dict = {"codigo_barras": codigo_barras.strip()}
    raw_body = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    timestamp_str = str(int(time.time()))
    nonce = secrets.token_hex(16)

    mensagem_hmac = f"{cfg['station_id']}\n{timestamp_str}\n{nonce}\n".encode("utf-8") + raw_body
    assinatura = hmac.new(
        cfg["station_secret"].encode("utf-8"), mensagem_hmac, hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Station-Id": cfg["station_id"],
        "X-Timestamp": timestamp_str,
        "X-Nonce": nonce,
        "X-Signature": assinatura,
    }

    try:
        resp = sessao.post(
            cfg["endpoint_verificar"],
            data=raw_body,
            headers=headers,
            timeout=cfg["timeout"],
            verify=cfg["verify_ssl"],
        )
        dados = resp.json() if resp.content else {}
        if resp.status_code == 200 and dados.get("autorizado") is True:
            return True, dados.get("mensagem", "Acesso permitido"), False

        motivo = dados.get("mensagem") or dados.get("erro") or f"HTTP {resp.status_code}"
        return False, motivo, False
    except requests.RequestException as exc:
        logger.error("Falha de comunicacao com o servidor (%s). Aplicando fail-closed (NEGADO).", exc)
        return False, "Servidor inacessivel", True
    except Exception as exc:
        logger.error("Erro inesperado na resposta da API: %s", exc)
        return False, "Resposta invalida do servidor", True


def monitorar_conectividade(sessao: requests.Session, cfg: dict, stop_event: threading.Event) -> None:
    """Thread em segundo plano que verifica periodicamente a recuperacao do servidor."""
    online_anterior = None
    while not stop_event.is_set():
        try:
            r = sessao.get(cfg["endpoint_health"], timeout=cfg["timeout"], verify=cfg["verify_ssl"])
            online_atual = r.status_code == 200
        except Exception:
            online_atual = False

        if online_atual and online_anterior is False:
            logger.info("Conexao com o servidor Rasporta RESTABELECIDA.")
        elif not online_atual and online_anterior is not False:
            logger.warning("Servidor Rasporta INACESSIVEL. Todas as leituras serao negadas ate reconexao.")

        online_anterior = online_atual
        stop_event.wait(15.0)


def ler_codigos_hid_direto(device_path: str):
    """
    Le eventos brutos de teclado USB HID (/dev/input/eventX) em ambiente headless (systemd).
    Formato struct input_event no Linux 64-bit: tv_sec (q), tv_usec (q), type (H), code (H), value (i) -> 24 bytes.
    """
    import struct

    formato = "qqHHi"
    tamanho = struct.calcsize(formato)
    buffer = []
    shift = False

    while True:
        try:
            with open(device_path, "rb") as dev:
                logger.info("Leitor HID conectado em %s", device_path)
                while True:
                    dados = dev.read(tamanho)
                    if not dados or len(dados) < tamanho:
                        break
                    _, _, ev_type, code, value = struct.unpack(formato, dados)
                    if ev_type != 1:  # EV_KEY
                        continue
                    if code in (42, 54):  # Shift
                        shift = value in (1, 2)
                        continue
                    if value == 1:  # Key press
                        if code in (28, 96):  # Enter / KP_Enter
                            codigo = "".join(buffer).strip()
                            buffer.clear()
                            if codigo:
                                yield codigo
                        elif code in EVDEV_KEYMAP:
                            caractere = EVDEV_KEYMAP[code]
                            buffer.append(caractere.upper() if shift else caractere)
        except FileNotFoundError:
            logger.error("Dispositivo HID %s nao encontrado. Tentando novamente em 5s...", device_path)
            time.sleep(5.0)
        except PermissionError:
            logger.critical("Sem permissao para ler %s. Adicione o usuario ao grupo 'input'.", device_path)
            time.sleep(10.0)
        except OSError as exc:
            logger.warning("Leitor HID desconectado (%s). Aguardando reconexao em 3s...", exc)
            time.sleep(3.0)


def ler_codigos_stdin():
    """Le codigos via entrada padrao (terminal interativo ou redirecionamento TTY)."""
    while True:
        linha = sys.stdin.readline()
        if not linha:
            time.sleep(0.5)
            continue
        codigo = linha.strip()
        if codigo:
            yield codigo


def iniciar_servico():
    cfg = carregar_config_estacao()
    sessao = criar_sessao_http()
    stop_event = threading.Event()

    def _parar(signum, frame):
        logger.info("Sinal %s recebido. Encerrando servico de verificacao...", signum)
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)

    logger.info("Iniciando Estacao '%s' -> API: %s", cfg["station_id"], cfg["endpoint_verificar"])

    thread_health = threading.Thread(
        target=monitorar_conectividade, args=(sessao, cfg, stop_event), daemon=True
    )
    thread_health.start()

    fonte_codigos = (
        ler_codigos_hid_direto(cfg["hid_device"]) if cfg["hid_device"] else ler_codigos_stdin()
    )

    for codigo in fonte_codigos:
        if stop_event.is_set():
            break
        autorizado, mensagem, erro_rede = consultar_autorizacao_api(sessao, cfg, codigo)
        if autorizado:
            logger.info("[PERMITIDO] Estacao=%s | %s", cfg["station_id"], mensagem)
            AcenderLuz(True, segundos=3.0)
        else:
            logger.warning("[NEGADO] Estacao=%s | Motivo=%s", cfg["station_id"], mensagem)
            if erro_rede:
                sinalizar_erro_rede()
            else:
                AcenderLuz(False, segundos=3.0)


if __name__ == "__main__":
    iniciar_servico()