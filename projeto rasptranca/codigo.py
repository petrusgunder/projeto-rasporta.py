import os
from datetime import timedelta
from flask import Flask, render_template, session
from banco_de_dados import BASE_DIR
from config_sistema import obter_secret_key
from usuarios import inicializar_admin_via_ambiente
from agenda import CriarLabsPadrao
from traducoes import traduzir

app = Flask(__name__)
app.secret_key = obter_secret_key(BASE_DIR)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RASPORTA_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
)

inicializar_admin_via_ambiente()
CriarLabsPadrao()

from routes import *  # noqa: E402, F401


@app.errorhandler(403)
def erro_403(e):
    idioma = session.get("idioma", "pt")
    return render_template("erro.html", codigo=403, mensagem=traduzir("msg_acesso_negado", idioma)), 403


@app.errorhandler(404)
def erro_404(e):
    return render_template("erro.html", codigo=404, mensagem="Página não encontrada / Página no encontrada."), 404


@app.errorhandler(500)
def erro_500(e):
    return render_template("erro.html", codigo=500, mensagem="Erro interno no servidor. Tente novamente."), 500


if __name__ == "__main__":
    host = os.environ.get("RASPORTA_HOST", "127.0.0.1")
    port = int(os.environ.get("RASPORTA_PORT", "5000"))
    debug_mode = os.environ.get("RASPORTA_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug_mode)