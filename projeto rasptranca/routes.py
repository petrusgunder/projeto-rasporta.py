# Trechos adicionados/atualizados em routes.py:
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from api_verificacao import (
    processar_requisicao_verificacao,
    cadastrar_estacao,
    rotacionar_chave_estacao,
    alternar_status_estacao,
    listar_estacoes,
    listar_logs_verificacao,
)


def _destino_seguro(url_destino: str | None, fallback: str) -> str:
    if url_destino and url_destino.startswith("/") and not url_destino.startswith("//"):
        return url_destino
    return fallback


@app.before_request
def proteger_csrf_global():
    # Endpoints de API usam autenticacao HMAC por estacao em vez de cookie de sessao
    if request.path.startswith("/api/v1/"):
        return None
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not validar_csrf_token(token):
            flash(t("msg_csrf_invalido"), "erro")
            return redirect(_destino_seguro(request.referrer, url_for("home")))


@app.after_request
def aplicar_cabecalhos_seguranca(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.route("/health")
def healthcheck():
    """Endpoint leve para Docker HEALTHCHECK e monitoramento."""
    try:
        ListarLaboratorios()
        return jsonify({"status": "ok"}), 200
    except Exception:
        return jsonify({"status": "erro"}), 503


@app.route("/api/v1/estacoes/verificar", methods=["POST"])
def api_verificar_estacao():
    """Endpoint autenticado via HMAC-SHA256 para verificacao fisica no Raspberry Pi."""
    raw_body = request.get_data() or b""
    dados_json = request.get_json(silent=True)
    ip_origem = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""

    status_code, payload = processar_requisicao_verificacao(
        station_id=request.headers.get("X-Station-Id", ""),
        timestamp_str=request.headers.get("X-Timestamp", ""),
        nonce=request.headers.get("X-Nonce", ""),
        assinatura_recebida=request.headers.get("X-Signature", ""),
        raw_body=raw_body,
        dados_json=dados_json,
        ip_origem=ip_origem,
    )
    return jsonify(payload), status_code


@app.route("/admin/estacoes", methods=["GET", "POST"])
@admin_required
def admin_estacoes():
    executor_id = session["usuario_id"]
    executor_nome = session["usuario_nome"]
    segredo_recem_gerado = None
    identificador_recem_gerado = None

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "cadastrar":
            identificador = request.form.get("identificador", "")
            nome = request.form.get("nome", "")
            id_lab = request.form.get("id_laboratorio", type=int) or 0
            ok, msg, segredo = cadastrar_estacao(
                identificador, nome, id_lab, executor_id=executor_id, executor_nome=executor_nome
            )
            flash(msg, "sucesso" if ok else "erro")
            if ok:
                segredo_recem_gerado = segredo
                identificador_recem_gerado = identificador.strip()
        elif acao == "rotacionar":
            id_est = request.form.get("id_estacao", type=int) or 0
            ok, msg, segredo = rotacionar_chave_estacao(
                id_est, executor_id=executor_id, executor_nome=executor_nome
            )
            flash(msg, "sucesso" if ok else "erro")
            if ok:
                segredo_recem_gerado = segredo
        elif acao == "alternar":
            id_est = request.form.get("id_estacao", type=int) or 0
            ok, msg = alternar_status_estacao(
                id_est, executor_id=executor_id, executor_nome=executor_nome
            )
            flash(msg, "sucesso" if ok else "erro")

    estacoes = listar_estacoes()
    labs = ListarLaboratorios()
    logs_fisicos = listar_logs_verificacao(limite=30)
    return render_template(
        "admin_estacoes.html",
        estacoes=estacoes,
        labs=labs,
        logs_fisicos=logs_fisicos,
        segredo_recem_gerado=segredo_recem_gerado,
        identificador_recem_gerado=identificador_recem_gerado,
    )