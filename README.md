# RaspTranca — Tranca Automática por Código de Barras

Projeto Integrador do **IFSC Campus Garopaba** — equipe **Petrus, Felipe e Martin ("Charlie")**.

O projeto se trata de um sistema de controle de acesso para laboratórios do ifsc: uma tranca automática que substitui chaves físicas. O acesso é liberado pela leitura de um **código de barras** cadastrado para cada pessoa, com saída num Raspberry Pi.

Além do controle físico, o sistema tem uma agenda de reserva de laboratórios com planilha visual de disponibilidade , login por usuário/senha.

---


## Como rodar o site de reservas

Abra a pasta onde que baixar o projeto e rode

```bash
git clone https://github.com/petrusgunder/projeto-rasporta.py.git

cd projeto-rasporta.py/"projeto rasptranca"

```

Depois dependendo do sistema operacional fara coisas diferentes

Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windols

```bash
python -m venv .venv
source .venv/bin/activate
```

Depois baixe o requirements.txt

```bash
pip install -r requirements.txt
```

Linux

```bash
python3 codigo.py
```

Windols

```bash
python codigo.py
```

Acesse **http://127.0.0.1:5000**


### Credenciais do administrador padrão

| Campo | Valor |
|---|---|
| Email | `admin@admin.com` |
| Senha | `admin127` |

O admin é criado automaticamente na primeira execução.
---

## Por que estas tecnologias?

**Flask** — O sistema precisa de rotas simples (login, reservas, CRUD) e integração com hardware, sem a complexidade de um framework gigante. Flask é leve, fácil de ler/estender (ideal para um PI técnico) e roda em qualquer PC ou Raspberry Pi.

**SQLite** — Perguntas: "quantos usuários?" ou "quantas reservas por dia?". A resposta: poucos, num único laboratório. SQLite é um banco em arquivo único (`banco.db`), sem servidor, zero configuração — perfeito para o porte e para um protótipo que precisa subir rápido no Pi.

**Jinja2 (templates)** — Motor de templates padrão do Flask. Permite renderizar as listas de usuários, labs e períodos no HTML de forma organizada, sem misturar muita lógica no servidor.

**HTML/CSS/JS puros** — Sem frameworks front-end. O dark mode usa **CSS variables** + `localStorage` (guarda a preferência no navegador), sem necessidade de biblioteca externa. Mantém o projeto simples e autossuficiente.

**Raspberry Pi + gpiozero** — O Pi é barato, popular em escolas/técnicos e tem GPIO para controlar LEDs. A biblioteca `gpiozero` deixa o código de hardware curto e legível. O módulo `rpi_luz.py` usa `try/import`: no PC ele *simula* os LEDs (imprime no console), no Pi ele acende os LEDs reais — o mesmo código roda nos dois lugares.

**werkzeug (hash de senhas)** — Já acompanha o Flask. Senhas nunca são guardadas em texto puro, só o hash. É o mínimo de segurança aceitável para um protótipo com login.

---


## Contatos

caso queira contribuir com o codigo envie um email para gunderiiitercerio@gmail.com