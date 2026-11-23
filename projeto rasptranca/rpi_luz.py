import logging
import os
import time

logger = logging.getLogger("rasporta.gpio")

PINO_LUZ_VERDE = int(os.environ.get("RASPORTA_GPIO_VERDE", "17"))
PINO_LUZ_VERMELHA = int(os.environ.get("RASPORTA_GPIO_VERMELHO", "27"))

try:
    from gpiozero import LED
    led_verde = LED(PINO_LUZ_VERDE)
    led_vermelha = LED(PINO_LUZ_VERMELHA)
    RASPBERRY_DISPONIVEL = True
except Exception as exc:
    led_verde = None
    led_vermelha = None
    RASPBERRY_DISPONIVEL = False
    logger.warning("GPIO indisponivel (%s). Operando em modo log/simulacao.", exc)


def _piscar(led, nome: str, segundos: float) -> None:
    if RASPBERRY_DISPONIVEL and led is not None:
        led.on()
        try:
            time.sleep(segundos)
        finally:
            led.off()
    else:
        logger.info("[SIMULACAO GPIO] LED %s aceso por %.1fs", nome, segundos)


def AcenderLuz(digital_encontrada: bool, segundos: float = 3.0) -> None:
    """Acende o LED verde se autorizado, ou o LED vermelho caso negado."""
    if digital_encontrada:
        _piscar(led_verde, "VERDE", segundos)
    else:
        _piscar(led_vermelha, "VERMELHA", segundos)


def sinalizar_erro_rede() -> None:
    """Pisca duas vezes o LED vermelho rapidamente para indicar falha de comunicacao."""
    for _ in range(2):
        _piscar(led_vermelha, "VERMELHA (ERRO REDE)", 0.35)
        time.sleep(0.2)