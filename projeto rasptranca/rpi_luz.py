import time

PINO_LUZ_VERDE = 17     # acende quando a leitura E valida
PINO_LUZ_VERMELHA = 27  # acende quando a leitura NAO e valida

try:
    from gpiozero import LED
    led_verde = LED(PINO_LUZ_VERDE)
    led_vermelha = LED(PINO_LUZ_VERMELHA)
    RASPBERRY_DISPONIVEL = True
except Exception:
    led_verde = None
    led_vermelha = None
    RASPBERRY_DISPONIVEL = False


def _piscar(led, nome, segundos):
    if RASPBERRY_DISPONIVEL:
        led.on()
        time.sleep(segundos)
        led.off()
    else:
        print(f"[SIMULAÇÃO] Luz {nome} acesa por {segundos}s (gpiozero indisponível nesse ambiente)")


def AcenderLuz(digital_encontrada, segundos=3):
    """
    Acende a luz verde se o usuario/codigo foi encontrado no banco,
    ou a luz vermelha caso contrario.
    """
    if digital_encontrada:
        _piscar(led_verde, "VERDE", segundos)
    else:
        _piscar(led_vermelha, "VERMELHA", segundos)