"""
Utilitario de linha de comando para criar ou promover um Administrador Principal
de forma segura diretamente no servidor / Raspberry Pi.

Uso:
    python3 criar_admin.py
"""
import getpass
from banco_de_dados import get_db, inicializar_banco
from usuarios import CadastrarUsuarioSistema, AlterarSenha, registrar_log_admin


def main():
    inicializar_banco()
    print("=" * 60)
    print("  RASPORTA - CONFIGURAÇÃO DE ADMINISTRADOR PRINCIPAL")
    print("=" * 60)

    email = input("E-mail institucional do administrador: ").strip().lower()
    if not email or "@" not in email:
        print("Erro: E-mail inválido.")
        return

    conn = get_db()
    existente = conn.execute(
        "SELECT id, nome, nivel_admin FROM SistemaUsuario WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    if existente:
        print(f"Usuário encontrado: {existente['nome']} (nível atual: {existente['nivel_admin']}).")
        resp = input("Deseja promovê-lo a Administrador Principal e redefinir a senha? [s/N]: ").strip().lower()
        if resp != "s":
            print("Operação cancelada.")
            return
        senha = getpass.getpass("Nova senha (mínimo 8 caracteres): ")
        confirma = getpass.getpass("Confirme a nova senha: ")
        if senha != confirma or len(senha) < 8:
            print("Erro: As senhas não conferem ou têm menos de 8 caracteres.")
            return

        AlterarSenha(existente["id"], senha)
        conn = get_db()
        try:
            with conn:
                conn.execute(
                    "UPDATE SistemaUsuario SET is_admin = 1, nivel_admin = 'super_admin' WHERE id = ?",
                    (existente["id"],),
                )
                registrar_log_admin(
                    conn,
                    existente["id"],
                    "CLI_RECOVERY",
                    "PROMOVER_SUPER_ADMIN",
                    f"Usuário '{email}' promovido a super_admin via terminal.",
                )
        finally:
            conn.close()
        print("Sucesso! Usuário promovido a Administrador Principal.")
    else:
        nome = input("Nome completo: ").strip()
        codigo_barras = input("Código de barras / crachá (opcional): ").strip() or None
        senha = getpass.getpass("Senha (mínimo 8 caracteres): ")
        confirma = getpass.getpass("Confirme a senha: ")
        if senha != confirma:
            print("Erro: As senhas não conferem.")
            return

        ok, msg = CadastrarUsuarioSistema(
            nome=nome,
            email=email,
            senha=senha,
            nivel_admin="super_admin",
            codigo_barras=codigo_barras,
            executor_nome="CLI_BOOTSTRAP",
        )
        print(msg)


if __name__ == "__main__":
    main()