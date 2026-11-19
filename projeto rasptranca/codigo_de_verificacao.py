import sys
from rpi_luz import AcenderLuz
from agenda import ListarLaboratorios, validar_acesso_fisico_codigo


def iniciar_verificacao_terminal():
    print("=" * 65)
    print("  SISTEMA DE CONTROLE DE ACESSO - IFSC CAMPUS GAROPABA")
    print("  Estação de Leitura por Código de Barras + Validação Temporal")
    print("=" * 65)

    labs = ListarLaboratorios()
    if not labs:
        print("Nenhum laboratório cadastrado no banco de dados.")
        return

    print("\nSelecione o laboratório associado a esta estação:")
    for lab in labs:
        print(f"  [{lab['id']}] {lab['nome']}")

    try:
        id_lab = int(input("\nID do laboratório: ").strip())
    except ValueError:
        print("ID inválido.")
        return

    lab_escolhido = next((l for l in labs if l["id"] == id_lab), None)
    if not lab_escolhido:
        print("Laboratório não encontrado.")
        return

    print(f"\nEstação vinculada ao: {lab_escolhido['nome']}")
    print("Aguardando leitura do código de barras... (Ctrl+C para encerrar)\n")

    while True:
        try:
            codigo = input("[Leitor] Código de Barras: ").strip()
            if not codigo:
                continue

            autorizado, detalhe = validar_acesso_fisico_codigo(codigo, id_lab)
            if autorizado:
                print(f"  [ACESSO PERMITIDO] {detalhe}")
                AcenderLuz(True, segundos=3)
            else:
                print(f"  [ACESSO NEGADO] {detalhe}")
                AcenderLuz(False, segundos=3)

        except KeyboardInterrupt:
            print("\nEncerrando estação de verificação...")
            sys.exit(0)
        except Exception as e:
            print(f"Erro ao processar leitura: {e}")


if __name__ == "__main__":
    iniciar_verificacao_terminal()