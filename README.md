# Mesa IPE

Consulta e acompanha Informações Periódicas e Eventuais (IPE) da CVM. A interface lê o banco local; um worker coleta os documentos em segundo plano.

## Requisitos

- Python 3.11+
- Conta CVM para o worker (`CVM_LOGIN` / `CVM_SENHA`)

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
```

O arquivo `.env` fica no seu ambiente local e não deve ser enviado para o Git. Ele é útil para desenvolvimento local, mas as credenciais reais ficam salvas no disco do seu computador.

Preencha suas credenciais da CVM no arquivo `.env`:

```env
CVM_LOGIN=seu_email@exemplo.com
CVM_SENHA=sua_senha
```

Se preferir, também é possível definir as variáveis diretamente no terminal antes de iniciar o worker ou o `poll`:

```powershell
$env:CVM_LOGIN="seu_email@exemplo.com"
$env:CVM_SENHA="sua_senha"
```

Essa abordagem é mais segura porque a senha fica apenas na sessão atual do terminal e não no projeto.

## Rodar

Interface (padrão: http://127.0.0.1:8765/):

```powershell
python -m cvm_poller serve
python -m cvm_poller serve --host 127.0.0.1 --port 8765
```

Coleta contínua:

```powershell
python -m cvm_poller worker
```

Uma coleta avulsa:

```powershell
python -m cvm_poller poll
```

Atualizar cadastro B3, nomes e datas de envio:

```powershell
python -m cvm_poller enrich
```

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `CVM_LOGIN` / `CVM_SENHA` | Obrigatórias no worker e em `poll` |
| `POLL_INTERVAL_SECONDS` | Intervalo do worker (mínimo 60; padrão 120) |
| `DATABASE_PATH` | SQLite (padrão `data/ipe.db`) |
| `APP_BASE_URL` | URL pública da app (links de acesso) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | E-mail (avisos ainda em desenvolvimento) |
| `TELEGRAM_BOT_TOKEN` | Telegram (ainda em desenvolvimento) |

Favoritos e “lido/não lido” ficam no navegador. Conta por e-mail, RSS e Telegram existem no backend, mas a UI ainda não usa.

## Consulta avulsa (CLI)

Ainda dá para baixar um recorte ao vivo em JSON, sem gravar no banco:

```powershell
python -m cvm_poller --source public --data 14/09/2026
python -m cvm_poller --source public --ticker PETR4 --data 14/09/2026
```

`--source login` usa Download Múltiplo e exige `CVM_LOGIN` / `CVM_SENHA`.

## Testes

```powershell
python -m pytest -q
```
