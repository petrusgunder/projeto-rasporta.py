from codigo import app
from flask import render_template, request, redirect, url_for, session, flash, abort
from autenticacao import (
    login_usuario_required,
    admin_required,
    gerar_csrf_token,
    validar_csrf_token,
    verificar_bloqueio_login,
    registrar_falha_login,
    limpar_falhas_login,
)
from config_sistema import agora_campus, CONFIG_PERIODOS, INTERVALOS_BLOQUEADOS
from traducoes import traduzir, IDIOMAS_SUPORTADOS, IDIOMA_PADRAO
from usuarios import (
    CadastrarUsuarioSistema,
    AutenticarUsuario,
    BuscarUsuarioSistema,
    ListarUsuariosSistema,
    EditarUsuarioSistema,
    ExcluirUsuarioSistema,
    listar_logs_admin,
)
from agenda import (
    ListarLaboratorios,
    CadastrarLaboratorio,
    EditarLaboratorio,
    ExcluirLaboratorio,
    ReservarLaboratorio,
    verificar_conflitos_recorrencia,
    confirmar_reserva_recorrente,
    DisponibilidadeDetalhadaNaData,
    ListarReservasFuturasDoUsuario,
    ListarReservasPassadasDoUsuario,
    ListarTodasReservas,
    ExcluirReserva,
    ExcluirSerieReservas,
    Periodos,
    validar_data_iso,
)


def _lang() -> str:
    lang = session.get("idioma") or request.cookies.get("idioma") or IDIOMA_PADRAO
    return lang if lang in IDIOMAS_SUPORTADOS else IDIOMA_PADRAO


def t(chave: str, **kwargs) -> str:
    return traduzir(chave, _lang(), **kwargs)


@app.before_request
def proteger_csrf_global():
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not validar_csrf_token(token):
            flash(t("msg_csrf_invalido"), "erro")
            return redirect(request.referrer or url_for("home"))


@app.context_processor
def contexto_global():
    idioma = _lang()
    nivel = session.get("usuario_nivel_admin", "usuario")
    return {
        "periodos": Periodos(),
        "config_periodos": CONFIG_PERIODOS,
        "intervalos_bloqueados": INTERVALOS_BLOQUEADOS,
        "hoje": agora_campus().date().isoformat(),
        "usuario_id_sessao": session.get("usuario_id"),
        "usuario_sessao": session.get("usuario_nome"),
        "usuario_eh_admin": nivel in ("admin", "super_admin"),
        "usuario_eh_super_admin": nivel == "super_admin",
        "usuario_nivel_admin": nivel,
        "csrf_token": gerar_csrf_token,
        "idioma_atual": idioma,
        "t": lambda chave, **kw: traduzir(chave, idioma, **kw),
    }


# =====================================================================
#  IDIOMA (PT-BR / ES)
# =====================================================================

@app.route("/idioma/<codigo>")
def trocar_idioma(codigo: str):
    if codigo in IDIOMAS_SUPORTADOS:
        session["idioma"] = codigo
    destino = request.referrer or url_for("home")
    resp = redirect(destino)
    if codigo in IDIOMAS_SUPORTADOS:
        resp.set_cookie("idioma", codigo, max_age=60 * 60 * 24 * 365, samesite="Lax", httponly=True)
    return resp


# =====================================================================
#  HOME (DISPONIBILIDADE + RESERVA SIMPLES E RECORRENTE)
# =====================================================================

@app.route("/")
def home():
    labs = ListarLaboratorios()
    hoje_dt = agora_campus().date()
    hoje = hoje_dt.isoformat()
    data_param = request.args.get("data", "")
    data_obj = validar_data_iso(data_param)
    data = data_obj.isoformat() if (data_obj and data_obj >= hoje_dt) else hoje

    grade = DisponibilidadeDetalhadaNaData(data)
    return render_template("home.html", labs=labs, data=data, grade=grade)


@app.route("/agenda")
def agenda():
    """Mantem compatibilidade redirecionando para a grade unificada na Home."""
    return redirect(url_for("home", data=request.args.get("data", "")))


@app.route("/reservar", methods=["POST"])
@login_usuario_required
def reservar():
    id_lab = request.form.get("laboratorio", type=int)
    data = request.form.get("data", "")
    periodo = request.form.get("periodo", type=int)
    descricao = request.form.get("descricao", "")

    ok, msg_chave = ReservarLaboratorio(session["usuario_id"], id_lab, data, periodo, descricao)
    flash(t(msg_chave), "sucesso" if ok else "erro")

    data_validada = validar_data_iso(data)
    destino_data = data_validada.isoformat() if data_validada else agora_campus().date().isoformat()
    return redirect(url_for("home", data=destino_data))


@app.route("/reservar_recorrente", methods=["POST"])
@login_usuario_required
def reservar_recorrente():
    etapa = request.form.get("etapa", "verificar")
    id_lab = request.form.get("laboratorio", type=int)
    dia_semana = request.form.get("dia_semana", type=int)
    data_inicio = request.form.get("data_inicio", "")
    data_fim = request.form.get("data_fim", "")
    periodo = request.form.get("periodo", type=int)
    descricao = request.form.get("descricao", "")

    if etapa == "verificar":
        ok, resultado = verificar_conflitos_recorrencia(id_lab, data_inicio, data_fim, dia_semana, periodo)
        if not ok:
            flash(t(resultado), "erro")
            return redirect(url_for("home"))

        # Se nao ha conflitos, cria diretamente em uma unica transacao (<= 3 cliques)
        if not resultado["conflitantes"]:
            ok_conf, msg_chave, extra = confirmar_reserva_recorrente(
                session["usuario_id"],
                id_lab,
                data_inicio,
                data_fim,
                dia_semana,
                periodo,
                descricao,
                modo="exigir_todas",
            )
            flash(t(msg_chave, **extra), "sucesso" if ok_conf else "erro")
            return redirect(url_for("home", data=data_inicio))

        # Se ha conflitos, exige decisao explicita do usuario
        labs = ListarLaboratorios()
        hoje = agora_campus().date().isoformat()
        grade = DisponibilidadeDetalhadaNaData(hoje)
        return render_template(
            "home.html",
            labs=labs,
            data=hoje,
            grade=grade,
            recorrencia_pendente={**resultado, "descricao": descricao},
        )

    elif etapa == "confirmar":
        modo = request.form.get("modo", "apenas_disponiveis")
        if modo not in ("apenas_disponiveis", "exigir_todas"):
            modo = "apenas_disponiveis"
        ok_conf, msg_chave, extra = confirmar_reserva_recorrente(
            session["usuario_id"],
            id_lab,
            data_inicio,
            data_fim,
            dia_semana,
            periodo,
            descricao,
            modo=modo,
        )
        flash(t(msg_chave, **extra), "sucesso" if ok_conf else "erro")
        return redirect(url_for("config") if ok_conf else url_for("home"))

    return redirect(url_for("home"))


# =====================================================================
#  LOGIN / LOGOUT
# =====================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id"):
        return redirect(url_for("home"))

    erro = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        chave_limite = f"{request.remote_addr}:{email}"

        bloqueado, segundos = verificar_bloqueio_login(chave_limite)
        if bloqueado:
            erro = t("msg_login_bloqueado", segundos=segundos)
            return render_template("login.html", erro=erro), 429

        usuario = AutenticarUsuario(email, senha)
        if usuario:
            limpar_falhas_login(chave_limite)
            idioma_preservado = _lang()
            session.clear()
            session.permanent = True
            session["idioma"] = idioma_preservado
            session["usuario_id"] = usuario["id"]
            session["usuario_nome"] = usuario["nome"]
            session["usuario_email"] = usuario["email"]
            session["usuario_nivel_admin"] = usuario["nivel_admin"]
            gerar_csrf_token()

            destino = (
                url_for("admin_dashboard")
                if usuario["nivel_admin"] in ("admin", "super_admin")
                else url_for("home")
            )
            return redirect(destino)

        registrar_falha_login(chave_limite)
        erro = t("msg_login_invalido")

    return render_template("login.html", erro=erro)


@app.route("/logout", methods=["POST"])
def logout():
    idioma_preservado = _lang()
    session.clear()
    session["idioma"] = idioma_preservado
    return redirect(url_for("home"))


# =====================================================================
#  MINHA CONTA & HISTORICO (FLUXOS UNIFICADOS)
# =====================================================================

@app.route("/config")
@login_usuario_required
def config():
    reservas = ListarReservasFuturasDoUsuario(session["usuario_id"])
    usuario = BuscarUsuarioSistema(session["usuario_id"])
    return render_template("config.html", reservas=reservas, usuario=usuario)


@app.route("/minhas_reservas")
@login_usuario_required
def minhas_reservas():
    """Unificado em Minha Conta (/config) para eliminar redundancia."""
    return redirect(url_for("config"))


@app.route("/historico")
@login_usuario_required
def historico():
    reservas = ListarReservasPassadasDoUsuario(session["usuario_id"])
    return render_template("historico.html", reservas=reservas)


@app.route("/cancelar_reserva/<int:id_reserva>", methods=["POST"])
@login_usuario_required
def cancelar_reserva(id_reserva: int):
    eh_admin = session.get("usuario_nivel_admin") in ("admin", "super_admin")
    ok, msg_chave = ExcluirReserva(
        id_reserva,
        session["usuario_id"],
        eh_admin=eh_admin,
        admin_nome=session.get("usuario_nome", "ADMIN"),
    )
    flash(t(msg_chave), "sucesso" if ok else "erro")
    destino = request.form.get("next") or request.referrer or url_for("config")
    return redirect(destino)


@app.route("/cancelar_serie/<serie_id>", methods=["POST"])
@login_usuario_required
def cancelar_serie(serie_id: str):
    eh_admin = session.get("usuario_nivel_admin") in ("admin", "super_admin")
    ok, msg_chave, qtd = ExcluirSerieReservas(
        serie_id,
        session["usuario_id"],
        eh_admin=eh_admin,
        admin_nome=session.get("usuario_nome", "ADMIN"),
    )
    flash(t(msg_chave, qtd=qtd), "sucesso" if ok else "erro")
    return redirect(url_for("config"))


# =====================================================================
#  PAINEL ADMINISTRATIVO
# =====================================================================

@app.route("/admin")
@admin_required
def admin_dashboard():
    usuarios = ListarUsuariosSistema()
    labs = ListarLaboratorios()
    reservas = ListarTodasReservas()
    logs = listar_logs_admin(limite=25)
    return render_template(
        "admin_dashboard.html",
        qtd_usuarios=len(usuarios),
        qtd_labs=len(labs),
        qtd_reservas=len(reservas),
        logs=logs,
    )


@app.route("/admin/usuarios", methods=["GET", "POST"])
@admin_required
def admin_usuarios():
    executor_id = session["usuario_id"]
    executor_nome = session["usuario_nome"]
    executor_nivel = session["usuario_nivel_admin"]

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "cadastrar":
            nome = request.form.get("nome", "")
            email = request.form.get("email", "")
            senha = request.form.get("senha", "")
            nivel_desejado = request.form.get("nivel_admin", "usuario")
            if executor_nivel != "super_admin" and nivel_desejado != "usuario":
                flash(t("msg_apenas_super_admin"), "erro")
                return redirect(url_for("admin_usuarios"))
            codigo_barras = request.form.get("codigo_barras", "")
            ok, msg = CadastrarUsuarioSistema(
                nome,
                email,
                senha,
                nivel_admin=nivel_desejado,
                codigo_barras=codigo_barras,
                executor_id=executor_id,
                executor_nome=executor_nome,
            )
            flash(msg, "sucesso" if ok else "erro")

        elif acao == "editar":
            id_usuario = request.form.get("id_usuario", type=int)
            nome = request.form.get("nome", "")
            email = request.form.get("email", "")
            nivel_desejado = request.form.get("nivel_admin", "usuario")
            codigo_barras = request.form.get("codigo_barras", "")
            ok, msg = EditarUsuarioSistema(
                id_usuario,
                nome,
                email,
                nivel_desejado,
                codigo_barras=codigo_barras,
                executor_id=executor_id,
                executor_nome=executor_nome,
                executor_nivel=executor_nivel,
            )
            flash(msg, "sucesso" if ok else "erro")

        elif acao == "excluir":
            id_usuario = request.form.get("id_usuario", type=int)
            ok, msg = ExcluirUsuarioSistema(
                id_usuario,
                executor_id=executor_id,
                executor_nome=executor_nome,
                executor_nivel=executor_nivel,
            )
            flash(msg, "sucesso" if ok else "erro")

        return redirect(url_for("admin_usuarios"))

    usuarios = ListarUsuariosSistema()
    return render_template("admin_usuarios.html", usuarios=usuarios)


@app.route("/admin/laboratorios", methods=["GET", "POST"])
@admin_required
def admin_laboratorios():
    executor_id = session["usuario_id"]
    executor_nome = session["usuario_nome"]

    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "cadastrar":
            ok, msg = CadastrarLaboratorio(
                request.form.get("nome", ""),
                request.form.get("descricao", ""),
                request.form.get("capacidade", type=int) or 30,
                executor_id=executor_id,
                executor_nome=executor_nome,
            )
            flash(msg, "sucesso" if ok else "erro")
        elif acao == "editar":
            ok, msg = EditarLaboratorio(
                request.form.get("id_lab", type=int),
                request.form.get("nome", ""),
                request.form.get("descricao", ""),
                request.form.get("capacidade", type=int) or 30,
                executor_id=executor_id,
                executor_nome=executor_nome,
            )
            flash(msg, "sucesso" if ok else "erro")
        elif acao == "excluir":
            ok, msg = ExcluirLaboratorio(
                request.form.get("id_lab", type=int),
                executor_id=executor_id,
                executor_nome=executor_nome,
            )
            flash(msg, "sucesso" if ok else "erro")

        return redirect(url_for("admin_laboratorios"))

    labs = ListarLaboratorios()
    return render_template("admin_laboratorios.html", labs=labs)


@app.route("/admin/reservas")
@admin_required
def admin_reservas():
    reservas = ListarTodasReservas()
    return render_template("admin_reservas.html", reservas=reservas)