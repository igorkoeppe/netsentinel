# Cenário local de teste do NetSentinel

Imagine um servidor que inicia um serviço autorizado, depois abre uma porta
inesperada e finalmente encerra os dois serviços. O roteiro usa conexões TCP reais
em `127.0.0.1` e verifica automaticamente os scans e alertas.

## 1. Testar sem banco

No PowerShell, na raiz do projeto:

```powershell
Set-Location C:\Dev\Netsentinel
.\.venv\Scripts\python.exe -m tools.demo_scenario
```

O script executa estas etapas:

1. Portas `18080` e `18081` fechadas: registra o baseline, sem alertas.
2. Abre `18080`, a porta autorizada: gera `EXPECTED_OPEN_PORT`, severidade `INFO`.
3. Abre `18081`: gera `UNEXPECTED_OPEN_PORT`, severidade `HIGH`.
4. Fecha as duas: gera dois alertas `PORT_CLOSED`, severidade `LOW`.

Resultado esperado: `PASSOU: 4 scans e 4 alertas com tipos e severidades corretos.`
O processo encerra os servidores locais ao terminar. Se as portas estiverem ocupadas,
use `--base-port 19080`, que seleciona `19080` e `19081`.

A política de portas desse cenário é definida apenas no script; seu `.env` permanece
inalterado. Nenhum webhook é enviado. Uma resposta TCP `CLOSED` comprova que o host
está acessível, então este roteiro não espera alertas `HOST_DOWN`.

## 2. Gravar os resultados

Com o PostgreSQL disponível, configure `DATABASE_URL` e `MIGRATION_DATABASE_URL`
no `.env`, seguindo o README. Para um banco novo:

```powershell
docker compose up -d db
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m tools.demo_scenario --persist
```

O script mostra os IDs de quatro scans e quatro alertas gravados. Cada nova execução
acrescenta registros; ela não apaga históricos nem faz triagem automaticamente.
Se o Docker Desktop ainda falhar ao iniciar, a etapa sem banco continua disponível.

## 3. Conferir no dashboard

Terminal A, na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe -m tools.demo_scenario --persist
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Copie a chave exibida para usar na interface. Ela vale apenas para esse processo da API.

Terminal B:

```powershell
Set-Location C:\Dev\Netsentinel\frontend
npm run dev
```

Abra `http://localhost:3000` (ou o endereço exibido pelo Vite) e siga:

1. Em **Settings**, mantenha `/api/v1` como URL, informe a chave e clique em
   **Save Credentials**, depois em **Test Connection**.
2. Em **Hosts**, procure `127.0.0.1` e confira os quatro scans pelos IDs impressos.
3. Em **Alerts**, filtre o alvo `127.0.0.1` e confira os quatro novos alertas em `OPEN`.
4. Abra o alerta `UNEXPECTED_OPEN_PORT` de severidade `HIGH`, clique em
   **Acknowledge** e confirme. O status deve mudar para `ACKNOWLEDGED`.
5. Clique em **Resolve** e confirme. O status deve mudar para `RESOLVED` e as ações
   de triagem devem desaparecer.
6. No **Overview**, confira a atualização das contagens. Históricos anteriores
   também entram nos totais; use os IDs para identificar os registros deste cenário.

O histórico de entregas desse cenário fica vazio porque o script não envia webhooks.

## 4. Conferir as correções da interface

- Em **Settings**, desligue o polling, limpe a chave e volte para **Alerts**.
  A API deve solicitar autenticação; os dados protegidos anteriores não devem aparecer.
  Insira e salve a chave novamente para recuperar o acesso.
- Para testar a falha de entregas, abra um alerta e use **Network request blocking**
  nas ferramentas do navegador para bloquear `*/api/v1/alerts/*/deliveries`.
  Recarregue a página: deve aparecer **Unable to load delivery history**, sem a
  mensagem de histórico vazio. Remova o bloqueio e clique em **Retry delivery history**.

## 5. Verificar regressões automatizadas

Na raiz:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q
```

Na pasta `frontend`:

```powershell
npm test
npm run build
```

O teste de concorrência de triagem exige `TEST_DATABASE_URL` apontando para um
PostgreSQL dedicado a testes. Não use a URL do banco com seus dados reais:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_concurrent_alert_triage_pg.py -q
```
