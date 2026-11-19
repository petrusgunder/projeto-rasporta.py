"""
Bateria automatizada dos 14 testes obrigatorios do Rasporta.py.
Executar com: python3 testes_sistema.py
"""
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta

# Isola banco temporario antes de importar a aplicacao
_TMP_DIR = tempfile.mkdtemp(prefix="rasporta_test_")
_TEST_DB = os.path.join(_TMP_DIR, "teste_banco.db")
os.environ["RASPORTA_DB_PATH"] = _TEST_DB
os.environ["RASPORTA_ADMIN_EMAIL"] = "super@ifsc.edu.br"
os.environ["RASPORTA_ADMIN_SENHA"] = "SenhaForte@2026"

from banco_de_dados import get_db, inicializar_banco  # noqa: E402
from config_sistema import FUSO_CAMPUS, periodo_ativo_no_momento, PERIODOS  # noqa: E402
from usuarios import CadastrarUsuarioSistema, EditarUsuarioSistema, ExcluirUsuarioSistema  # noqa: E402
from agenda import (  # noqa: E402
    CriarLabsPadrao,
    ListarLaboratorios,
    ReservarLaboratorio,
    verificar_conflitos_recorrencia,
    confirmar_reserva_recorrente,
    ExcluirSerieReservas,
    validar_acesso_fisico_codigo,
)
from codigo import app  # noqa: E402


class TestesRasportaCompleto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CriarLabsPadrao(_TEST_DB)
        CadastrarUsuarioSistema("Docente Ana", "ana@ifsc.edu.br", "SenhaAna123", "usuario", "111222333", db_path=_TEST_DB)
        CadastrarUsuarioSistema("Docente Bruno", "bruno@ifsc.edu.br", "SenhaBruno123", "usuario", "444555666", db_path=_TEST_DB)
        CadastrarUsuarioSistema("Admin Comum", "admincomum@ifsc.edu.br", "SenhaAdmin123", "admin", "777888999", db_path=_TEST_DB)

        conn = get_db(_TEST_DB)
        cls.super_id = conn.execute("SELECT id FROM SistemaUsuario WHERE email='super@ifsc.edu.br'").fetchone()["id"]
        cls.admin_id = conn.execute("SELECT id FROM SistemaUsuario WHERE email='admincomum@ifsc.edu.br'").fetchone()["id"]
        cls.ana_id = conn.execute("SELECT id FROM SistemaUsuario WHERE email='ana@ifsc.edu.br'").fetchone()["id"]
        cls.bruno_id = conn.execute("SELECT id FROM SistemaUsuario WHERE email='bruno@ifsc.edu.br'").fetchone()["id"]
        cls.lab_id = ListarLaboratorios(_TEST_DB)[0]["id"]
        conn.close()

    def _login(self, client, email, senha):
        resp_get = client.get("/login")
        html = resp_get.data.decode("utf-8")
        token = html.split('name="csrf_token" value="')[1].split('"')[0]
        return client.post("/login", data={"csrf_token": token, "email": email, "senha": senha}, follow_redirects=True)

    def _csrf(self, client):
        with client.session_transaction() as sess:
            return sess["_csrf_token"]

    def test_01_concorrencia_simultanea_mesmo_horario(self):
        amanha = (datetime.now(FUSO_CAMPUS).date() + timedelta(days=5)).isoformat()
        resultados = []
        barreira = threading.Barrier(2)

        def tentar(uid):
            barreira.wait()
            ok, msg = ReservarLaboratorio(uid, self.lab_id, amanha, 1, "Aula Concorrente", db_path=_TEST_DB)
            resultados.append((ok, msg))

        t1 = threading.Thread(target=tentar, args=(self.ana_id,))
        t2 = threading.Thread(target=tentar, args=(self.bruno_id,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        sucessos = [r for r in resultados if r[0]]
        falhas = [r for r in resultados if not r[0]]
        self.assertEqual(len(sucessos), 1)
        self.assertEqual(len(falhas), 1)
        self.assertEqual(falhas[0][1], "msg_reserva_conflito")

    def test_02_data_passada(self):
        ontem = (datetime.now(FUSO_CAMPUS).date() - timedelta(days=1)).isoformat()
        ok, msg = ReservarLaboratorio(self.ana_id, self.lab_id, ontem, 2, db_path=_TEST_DB)
        self.assertFalse(ok)
        self.assertEqual(msg, "msg_data_passada")

    def test_03_periodo_ja_iniciado(self):
        ref = datetime(2026, 11, 19, 10, 15, tzinfo=FUSO_CAMPUS)
        ok, msg = ReservarLaboratorio(self.ana_id, self.lab_id, "2026-11-19", 1, momento_ref=ref, db_path=_TEST_DB)
        self.assertFalse(ok)
        self.assertEqual(msg, "msg_periodo_iniciado")

    def test_04_laboratorio_inexistente(self):
        futuro = (datetime.now(FUSO_CAMPUS).date() + timedelta(days=6)).isoformat()
        ok, msg = ReservarLaboratorio(self.ana_id, 999999, futuro, 2, db_path=_TEST_DB)
        self.assertFalse(ok)
        self.assertEqual(msg, "msg_lab_invalido")

    def test_05_cancelar_reserva_de_outro_usuario(self):
        futuro = (datetime.now(FUSO_CAMPUS).date() + timedelta(days=7)).isoformat()
        ok, _ = ReservarLaboratorio(self.ana_id, self.lab_id, futuro, 3, db_path=_TEST_DB)
        self.assertTrue(ok)

        conn = get_db(_TEST_DB)
        res_id = conn.execute(
            "SELECT id FROM Reserva WHERE id_usuario=? AND data_reserva=? AND periodo=3",
            (self.ana_id, futuro),
        ).fetchone()["id"]
        conn.close()

        client = app.test_client()
        self._login(client, "bruno@ifsc.edu.br", "SenhaBruno123")
        token = self._csrf(client)
        client.post(f"/cancelar_reserva/{res_id}", data={"csrf_token": token})

        conn = get_db(_TEST_DB)
        ainda_existe = conn.execute("SELECT 1 FROM Reserva WHERE id=?", (res_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(ainda_existe)

    def test_06_acesso_admin_sem_autorizacao(self):
        client = app.test_client()
        self._login(client, "ana@ifsc.edu.br", "SenhaAna123")
        resp = client.get("/admin", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/", resp.headers["Location"])

    def test_07_escalada_privilegios_bloqueada(self):
        # Admin comum tentando promover usuario a super_admin ou remover ultimo super_admin
        ok_prom, _ = EditarUsuarioSistema(
            self.ana_id,
            "Docente Ana",
            "ana@ifsc.edu.br",
            "super_admin",
            executor_id=self.admin_id,
            executor_nome="Admin Comum",
            executor_nivel="admin",
            db_path=_TEST_DB,
        )
        self.assertFalse(ok_prom)

        ok_demote, _ = EditarUsuarioSistema(
            self.super_id,
            "Administrador Principal",
            "super@ifsc.edu.br",
            "usuario",
            executor_id=self.super_id,
            executor_nome="Super",
            executor_nivel="super_admin",
            db_path=_TEST_DB,
        )
        self.assertFalse(ok_demote)

    def test_08_recorrente_todas_disponiveis(self):
        base = datetime.now(FUSO_CAMPUS).date() + timedelta(days=14)
        # Encontra proxima quarta-feira (weekday == 2)
        while base.weekday() != 2:
            base += timedelta(days=1)
        fim = base + timedelta(days=14)  # 3 quartas-feiras

        ok, msg, extra = confirmar_reserva_recorrente(
            self.ana_id, self.lab_id, base.isoformat(), fim.isoformat(), 2, 4, "Disciplina Redes", modo="exigir_todas", db_path=_TEST_DB
        )
        self.assertTrue(ok)
        self.assertEqual(extra["qtd"], 3)
        self._serie_criada = extra["serie_id"]
        self._datas_serie = [base.isoformat(), (base + timedelta(days=7)).isoformat(), fim.isoformat()]

    def test_09_recorrente_com_conflito(self):
        base = datetime.now(FUSO_CAMPUS).date() + timedelta(days=40)
        while base.weekday() != 4:  # sexta-feira
            base += timedelta(days=1)
        segunda_ocorrencia = base + timedelta(days=7)
        fim = base + timedelta(days=14)

        # Bruno ocupa a segunda sexta-feira
        ReservarLaboratorio(self.bruno_id, self.lab_id, segunda_ocorrencia.isoformat(), 5, db_path=_TEST_DB)

        ok, analise = verificar_conflitos_recorrencia(
            self.lab_id, base.isoformat(), fim.isoformat(), 4, 5, db_path=_TEST_DB
        )
        self.assertTrue(ok)
        self.assertEqual(len(analise["disponiveis"]), 2)
        self.assertEqual(len(analise["conflitantes"]), 1)
        self.assertEqual(analise["conflitantes"][0]["data"], segunda_ocorrencia.isoformat())

    def test_10_e_11_cancelamento_individual_e_serie(self):
        base = datetime.now(FUSO_CAMPUS).date() + timedelta(days=70)
        while base.weekday() != 0:
            base += timedelta(days=1)
        fim = base + timedelta(days=21)  # 4 segundas-feiras

        ok, _, extra = confirmar_reserva_recorrente(
            self.bruno_id, self.lab_id, base.isoformat(), fim.isoformat(), 0, 6, "Lab Prog", db_path=_TEST_DB
        )
        self.assertTrue(ok)
        serie_id = extra["serie_id"]

        # Cancela 1 ocorrencia individualmente
        conn = get_db(_TEST_DB)
        primeira_id = conn.execute(
            "SELECT id FROM Reserva WHERE serie_id=? ORDER BY data_reserva ASC LIMIT 1", (serie_id,)
        ).fetchone()["id"]
        conn.execute("DELETE FROM Reserva WHERE id=?", (primeira_id,))
        conn.commit()
        restantes = conn.execute("SELECT COUNT(*) FROM Reserva WHERE serie_id=?", (serie_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(restantes, 3)

        # Cancela toda a serie restante
        ok_s, _, qtd_removida = ExcluirSerieReservas(serie_id, self.bruno_id, db_path=_TEST_DB)
        self.assertTrue(ok_s)
        self.assertEqual(qtd_removida, 3)

    def test_12_alternancia_pt_es(self):
        client = app.test_client()
        resp_es = client.get("/idioma/es", follow_redirects=True)
        self.assertIn("Reserve su Laboratorio", resp_es.data.decode("utf-8"))

        resp_pt = client.get("/idioma/pt", follow_redirects=True)
        self.assertIn("Reserve seu Laboratório", resp_pt.data.decode("utf-8"))

    def test_13_horario_noturno_e_intervalo_20min(self):
        self.assertEqual(PERIODOS[8], "19:00 - 20:20")
        self.assertEqual(PERIODOS[9], "20:40 - 22:00")

        # Durante o intervalo (20:30), nenhum periodo deve estar ativo e acesso comum e negado
        no_intervalo = datetime(2026, 11, 25, 20, 30, tzinfo=FUSO_CAMPUS)
        self.assertIsNone(periodo_ativo_no_momento(no_intervalo))

        # No Periodo 9 (21:00) com reserva valida, o codigo de barras libera acesso
        data_noturna = "2026-11-25"
        ReservarLaboratorio(self.ana_id, self.lab_id, data_noturna, 9, "Aula Noturna", db_path=_TEST_DB)
        no_periodo_9 = datetime(2026, 11, 25, 21, 0, tzinfo=FUSO_CAMPUS)
        permitido, _ = validar_acesso_fisico_codigo("111222333", self.lab_id, momento=no_periodo_9, db_path=_TEST_DB)
        self.assertTrue(permitido)

        negado_intervalo, _ = validar_acesso_fisico_codigo("111222333", self.lab_id, momento=no_intervalo, db_path=_TEST_DB)
        self.assertFalse(negado_intervalo)

    def test_14_migracao_preserva_dados(self):
        legacy_db = os.path.join(_TMP_DIR, "legacy.db")
        conn = sqlite3.connect(legacy_db)
        conn.executescript("""
            CREATE TABLE SistemaUsuario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL UNIQUE,
                senha_hash VARCHAR(200) NOT NULL,
                is_admin BOOLEAN NOT NULL DEFAULT 0
            );
            INSERT INTO SistemaUsuario (nome, email, senha_hash, is_admin)
            VALUES ('Prof Antigo', 'antigo@ifsc.edu.br', 'hash_existente', 1);
        """)
        conn.commit()
        conn.close()

        inicializar_banco(legacy_db)
        conn2 = get_db(legacy_db)
        row = conn2.execute("SELECT nome, nivel_admin FROM SistemaUsuario WHERE email='antigo@ifsc.edu.br'").fetchone()
        conn2.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["nome"], "Prof Antigo")
        self.assertEqual(row["nivel_admin"], "super_admin")


if __name__ == "__main__":
    unittest.main(verbosity=2)