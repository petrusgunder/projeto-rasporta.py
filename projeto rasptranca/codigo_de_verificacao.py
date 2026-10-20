import sys
from rpi_luz import AcenderLuz
from usuarios import BuscarUsuarioPorCodigoBarras


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

            # Busca diretamente no sistema sem validar a formatação/EAN-13
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
