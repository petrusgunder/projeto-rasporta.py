import sys
from rpi_luz import AcenderLuz
from usuarios import BuscarUsuarioPorCodigoBarras


def validar_ean13(codigo: str) -> bool:
    """
    Valida se a string fornecida é um código EAN-13 válido:
    1. Deve possuir exatamente 13 dígitos numéricos.
    2. O 13º dígito deve ser igual ao dígito verificador calculado.
    """
    if not codigo.isdigit() or len(codigo) != 13:
        return False

    soma = 0
    for i in range(12):
        digito = int(codigo[i])
        soma += digito * 1 if i % 2 == 0 else digito * 3

    digito_calculado = (10 - (soma % 10)) % 10
    digito_real = int(codigo[12])

    return digito_calculado == digito_real


def iniciar_verificacao_terminal():
    print("=" * 60)
    print("  SISTEMA DE VERIFICAÇÃO DE CÓDIGO DE BARRAS (TERMINAL)")
    print("  Aguardando leitura do código... (Pressione Ctrl+C para sair)")
    print("=" * 60)

    while True:
        try:
            codigo = input("\n[Aguardando Leitura] Informe o Código de Barras: ").strip()

            if not codigo:
                continue

            if not validar_ean13(codigo):
                print(f" ⚠️ [CÓDIGO INVÁLIDO] '{codigo}' não é um EAN-13 válido (tamanho incorreto ou dígito verificador falhou)!")
                AcenderLuz(False, segundos=1)
                continue

            usuario = BuscarUsuarioPorCodigoBarras(codigo)

            if usuario:
                nome_usuario = usuario[1]
                print(f" [ACESSO PERMITIDO] Usuário Encontrado: {nome_usuario}")
                AcenderLuz(True, segundos=3)
            else:
                print(f" [ACESSO NEGADO] Código de barras '{codigo}' não cadastrado!")
                AcenderLuz(False, segundos=3)

        except KeyboardInterrupt:
            print("\n\nSaindo do sistema de verificação por terminal...")
            sys.exit(0)
        except Exception as e:
            print(f"Ocorreu um erro durante o processamento: {e}")


if __name__ == "__main__":
    iniciar_verificacao_terminal()