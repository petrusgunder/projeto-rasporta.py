# Adicao a classe TestesRasportaCompleto em teste_sistema.py:
import hashlib
import hmac
import json
import time
from api_verificacao import cadastrar_estacao, assinar_payload_estacao
from banco_de_dados import criar_backup_banco, restaurar_backup_banco
from codigo_de_verificacao import consultar_autorizacao_api


    def test_15_e_16_api_estacao_autorizacao_e_negacao(self):
        ok, _, segredo = cadastrar_estacao("estacao-teste-1", "Porta Lab 1", self.lab_id, db_path=_TEST_DB)
        self.assertTrue(ok)

        # Reserva para hoje no periodo 2 (09:00 - 09:50)
        hoje_str = datetime.now(FUSO_CAMPUS).date().isoformat()
        conn = get_db(_TEST_DB)
        conn.execute(
            "INSERT OR IGNORE INTO Reserva (id_usuario, id_laboratorio, data_reserva, periodo, descricao) "
            "VALUES (?, ?, ?, 2, 'Teste API')",
            (self.ana_id, self.lab_id, hoje_str),
        )
        conn.commit()
        conn.close()

        client = app.test_client()

        def enviar_api(codigo_barras, nonce_custom=None, ts_custom=None, sig_custom=None):
            body = json.dumps({"codigo_barras": codigo_barras}, separators=(",", ":")).encode("utf-8")
            ts = ts_custom or str(int(time.time()))
            nonce = nonce_custom or f"nonce_{time.time_ns()}"
            sig = sig_custom or assinar_payload_estacao("estacao-teste-1", ts, nonce, body, segredo)
            return client.post(
                "/api/v1/estacoes/verificar",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Station-Id": "estacao-teste-1",
                    "X-Timestamp": ts,
                    "X-Nonce": nonce,
                    "X-Signature": sig,
                },
            )

        # Admin tem acesso permanente via API
        resp_admin = enviar_api("777888999")
        self.assertEqual(resp_admin.status_code, 200)
        self.assertTrue(resp_admin.get_json()["autorizado"])
        self.assertEqual(resp_admin.get_json()["led"], "verde")

        # Codigo inexistente e negado com LED vermelho
        resp_invalido = enviar_api("000000000")
        self.assertEqual(resp_invalido.status_code, 200)
        self.assertFalse(resp_invalido.get_json()["autorizado"])
        self.assertEqual(resp_invalido.get_json()["led"], "vermelho")

    def test_17_api_bloqueia_assinatura_invalida_e_replay(self):
        ok, _, segredo = cadastrar_estacao("estacao-sec-1", "Porta Seguranca", self.lab_id, db_path=_TEST_DB)
        self.assertTrue(ok)
        client = app.test_client()

        body = json.dumps({"codigo_barras": "777888999"}, separators=(",", ":")).encode("utf-8")
        ts = str(int(time.time()))
        nonce = f"replay_{time.time_ns()}"
        sig_valida = assinar_payload_estacao("estacao-sec-1", ts, nonce, body, segredo)

        headers = {
            "Content-Type": "application/json",
            "X-Station-Id": "estacao-sec-1",
            "X-Timestamp": ts,
            "X-Nonce": nonce,
            "X-Signature": sig_valida,
        }
        r1 = client.post("/api/v1/estacoes/verificar", data=body, headers=headers)
        self.assertEqual(r1.status_code, 200)

        # Segunda requisicao com mesmo nonce deve ser bloqueada (HTTP 409)
        r2 = client.post("/api/v1/estacoes/verificar", data=body, headers=headers)
        self.assertEqual(r2.status_code, 409)

        # Assinatura adulterada deve ser bloqueada (HTTP 401)
        headers["X-Nonce"] = f"novo_{time.time_ns()}"
        headers["X-Signature"] = "0" * 64
        r3 = client.post("/api/v1/estacoes/verificar", data=body, headers=headers)
        self.assertEqual(r3.status_code, 401)

    def test_18_cliente_verificador_fail_closed_sem_internet(self):
        import requests
        cfg_offline = {
            "endpoint_verificar": "http://127.0.0.1:59999/api/v1/estacoes/verificar",
            "station_id": "estacao-offline",
            "station_secret": "a" * 64,
            "timeout": 0.2,
            "verify_ssl": False,
        }
        autorizado, motivo, erro_rede = consultar_autorizacao_api(requests.Session(), cfg_offline, "777888999")
        self.assertFalse(autorizado)
        self.assertTrue(erro_rede)

    def test_19_backup_e_restauracao_a_quente(self):
        bkp = criar_backup_banco(_TEST_DB, destino_dir=_TMP_DIR)
        self.assertTrue(os.path.exists(bkp))
        restaurar_backup_banco(bkp, _TEST_DB)
        conn = get_db(_TEST_DB)
        qtd = conn.execute("SELECT COUNT(*) FROM SistemaUsuario").fetchone()[0]
        conn.close()
        self.assertGreaterEqual(qtd, 4)