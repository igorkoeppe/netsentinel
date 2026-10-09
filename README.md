# NetSentinel

Uma ferramenta educacional e defensiva de monitoramento e análise de conectividade TCP, desenvolvida como projeto de Engenharia da Computação com foco em cybersecurity.

## Features

- Validação rigorosa de alvos (IPv4, IPv6 e hostnames).
- Probes TCP assíncronos de alta performance.
- Scanner concorrente de múltiplas portas com limite controlável.
- Detecção de disponibilidade do host via TCP (inferência por portas `OPEN` ou `CLOSED`).
- Medição de tempo de resposta baseada no TCP handshake.
- CLI amigável (`netsentinel`).
- Camada de persistência transacional com PostgreSQL (`--persist`).
- Histórico persistido de monitoramento e detalhes de scan (`netsentinel history`).
- Motor de alertas de segurança (`Alert Engine`) com regras determinísticas e severidades configuráveis.
- Política de portas TCP esperadas (`EXPECTED_TCP_PORTS`).
- Ciclo de vida e triagem de alertas de segurança (`netsentinel alerts acknowledge/resolve`).
- Entrega de notificações e webhooks em tempo real (`NotificationPolicy`, `WebhookNotificationSender`).
- Auditoria e persistência de histórico de entregas de notificações no PostgreSQL (`notification_deliveries`).
- API HTTP REST versionada (`/api/v1`) com FastAPI, OpenAPI interativo (`/docs`, `/redoc`), autenticação via header `X-API-Key`, triagem remota e CORS configurável.
- Dashboard Web defensivo moderno em React + TypeScript strict com métricas operacionais, gráficos de status e severidade, busca de hosts, histórico global de scans, triagem interativa de alertas e suporte a temas (dark/light/system).

## Arquitetura

```text
       ┌───────────┐         ┌─────────────────────────┐
       │    CLI    │         │  Dashboard (React + TS) │
       └─────┬─────┘         └────────────┬────────────┘
             │                            │ HTTP / JSON
             │                            ▼
             │               ┌─────────────────────────┐
             │               │   REST API (/api/v1)    │
             │               └────────────┬────────────┘
             ▼                            ▼
      ┌───────────────────────────────────────────────┐
      │             Application Services              │
      │ (HostQuery, History, AlertQuery, Dashboard,   │
      │  AlertTriage, NotificationDelivery, ...)      │
      └──────────────────────┬────────────────────────┘
                             │
                             ▼
      ┌───────────────────────────────────────────────┐
      │             Repositories / Models             │
      │      (Host, Scan, Event, Alert, Delivery)     │
      └──────────────────────┬────────────────────────┘
                             │
                             ▼
      ┌───────────────────────────────────────────────┐
      │              PostgreSQL Database              │
      └───────────────────────────────────────────────┘
```

## Instalação

```bash
# Clone o repositório
git clone <repository-url>
cd Projeto_NetSentinel

# Crie e ative o ambiente virtual
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\Activate.ps1

# Instale o projeto localmente
pip install -e .
```

## Quick Start

Execute a CLI para verificar as opções:

```bash
netsentinel --help
netsentinel scan --help
```

## Exemplos

Escaneando portas específicas de um alvo local:

```bash
netsentinel scan 127.0.0.1 --ports 22,80,443,8000
```

**Saída Aproximada:**
```text
NetSentinel TCP Scan

Target: 127.0.0.1
Status: AVAILABLE
Response time: 1.0 ms

PORT     STATUS       TIME
22       CLOSED       2036.9 ms
80       CLOSED       2036.5 ms
443      CLOSED       2036.3 ms
8000     OPEN         1.0 ms

4 ports scanned
1 open
3 closed
```

### Continuous Monitoring (v0.2.0)

### View History

Você pode consultar o histórico de monitoramento persistido de um host específico. Os dados incluem informações sobre o status de disponibilidade do host, detalhes sobre portas verificadas, eventos de estado e contagem de security alerts ao longo do tempo.

> **Nota:** A consulta de histórico requer o PostgreSQL rodando (por exemplo, via `docker compose up -d db`), a variável `DATABASE_URL` configurada, e as migrations aplicadas (`alembic upgrade head`).

Para visualizar os scans mais recentes de um host (incluindo contadores de portas, eventos e alertas):

```bash
netsentinel history 192.168.1.5
```

Por padrão, os 10 scans mais recentes são exibidos. Você pode modificar esse limite utilizando a flag `--limit`:

```bash
netsentinel history 192.168.1.5 --limit 5
```

Para inspecionar um scan específico e visualizar as informações de portas testadas, os eventos de mudança detectados e os alertas de segurança gerados:

```bash
netsentinel history --scan 42
```

### Security Alerts & Triage (v0.5.0)

Você pode visualizar a fila de alertas de segurança persistidos através do comando `alerts`:

```bash
netsentinel alerts
```

Por padrão, os 20 alertas mais recentes são exibidos. Você pode modificar esse limite utilizando a flag `--limit`:

```bash
netsentinel alerts --limit 50
```

**Saída Aproximada:**
```text
NetSentinel Security Alerts

ID     SEVERITY   TYPE                   STATUS         TARGET           PORT     CREATED
42     HIGH       UNEXPECTED_OPEN_PORT   OPEN           127.0.0.1        8080     2026-09-08 15:30:00
41     LOW        PORT_CLOSED            ACKNOWLEDGED   127.0.0.1        22       2026-09-08 15:20:00
40     MEDIUM     HOST_DOWN              RESOLVED       127.0.0.1        -        2026-09-08 15:00:00
```

#### Filtros de Consulta (`--status` e `--severity`)

A listagem de alertas suporta filtros opcionais combinados via lógica `AND`, aplicados diretamente na consulta do PostgreSQL (sem carregamento desnecessário na memória):

```bash
# Filtrar apenas alertas abertos
netsentinel alerts --status OPEN

# Filtrar por severidade alta
netsentinel alerts --severity HIGH

# Combinar filtros de status e severidade
netsentinel alerts --status OPEN --severity HIGH

# Combinar filtros com limite customizado de paginação
netsentinel alerts --status OPEN --severity HIGH --limit 10
```

**Valores válidos para `--status`:**
- `OPEN`
- `ACKNOWLEDGED`
- `RESOLVED`

*(A entrada é case-insensitive, aceitando por exemplo `open`, `Open` ou `OPEN`).*

**Valores válidos para `--severity`:**
- `INFO`
- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

*(A entrada é case-insensitive, aceitando por exemplo `high`, `High` ou `HIGH`).*

#### Ações de Triagem na CLI

Alertas de segurança suportam transições explícitas de estado através dos subcomandos `acknowledge` e `resolve`:

1. **Reconhecer um alerta (`OPEN -> ACKNOWLEDGED`):**
   ```bash
   netsentinel alerts acknowledge 42
   ```

2. **Resolver um alerta reconhecido (`ACKNOWLEDGED -> RESOLVED`):**
   ```bash
   netsentinel alerts resolve 42
   ```

3. **Resolver diretamente um alerta aberto (`OPEN -> RESOLVED`):**
   ```bash
   netsentinel alerts resolve 42
   ```

> **Nota:** Transições inválidas (como tentar reconhecer um alerta já resolvido ou repetir um reconhecimento) são rejeitadas com mensagem explicativa. Reabertura (`RESOLVED -> OPEN`) ainda não é suportada nesta etapa.


O projeto possui dois modos principais de execução. O primeiro é o `scan` sob demanda:

```bash
netsentinel scan 127.0.0.1 --ports 22,80,443
```

E o segundo é o monitoramento contínuo usando o comando `monitor`:

```bash
netsentinel monitor 127.0.0.1 --ports 22,80,443 --interval 30
```

Você também pode limitar a quantidade de snapshots usando `--count`:

```bash
netsentinel monitor 127.0.0.1 --ports 80,443 --interval 5 --count 10
```

#### Como funciona o monitoramento contínuo
O fluxo simplificado é o seguinte:
```text
scan -> snapshot -> wait -> scan -> snapshot -> compare -> events -> alerts
```

O primeiro snapshot apenas estabelece o baseline da sessão em memória, não gerando falsos positivos ou eventos artificiais. A partir do segundo snapshot, o motor passa a detectar as seguintes **mudanças observadas entre snapshots consecutivos**:

- `PORT_OPENED`
- `PORT_CLOSED`
- `HOST_BECAME_AVAILABLE`
- `HOST_BECAME_UNAVAILABLE`

Esses eventos representam alterações concretas no estado e não são varreduras de vulnerabilidade e não funcionam como um IDS completo.

Cada evento detectado é avaliado pelo Alert Engine, que gera **security alerts** classificados por severidade (`INFO`, `LOW`, `MEDIUM`, `HIGH`). Os alerts são exibidos em tempo real após os eventos que os originaram.

O comando irá executar indefinitamente ou até atingir o limite estipulado em `--count`. Se interrompido manualmente pelo usuário com `Ctrl+C` ou finalizado naturalmente, um resumo da sessão é exibido informando a quantidade de snapshots realizados, eventos detectados, alertas gerados (agrupados por severidade) e a duração.

> Sem `--persist`, os snapshots e alertas são mantidos apenas em memória durante a execução para exibição imediata e resumo final. Com `--persist`, cada ciclo (Scan, PortResults, MonitoringEvents e SecurityAlerts) é persistido atomicamente no PostgreSQL.

## Como funciona

### Detecção de estado da porta
- **OPEN**: Conexão TCP estabelecida com sucesso.
- **CLOSED**: O host respondeu recusando a conexão (`ConnectionRefusedError`). Isso significa que a máquina está ativa, mas o serviço está inativo ou protegido, o que ainda é prova de disponibilidade.
- **TIMEOUT / UNREACHABLE**: Sem resposta clara ou bloqueio silencioso por firewall.

### Disponibilidade TCP
> Na v0.1, disponibilidade e tempo de resposta são inferidos através de conexões TCP. O NetSentinel ainda não implementa ICMP ping.

Se ao menos uma porta retornar `OPEN` ou `CLOSED`, o host é considerado `AVAILABLE`. O tempo de resposta será o menor tempo entre os probes respondidos.

### PostgreSQL Persistence (Optional)

With the `--persist` flag, `netsentinel monitor` saves the complete cycle atomically into PostgreSQL:
- Upserts the **Host**
- Creates a new **Scan** record
- Logs **Port Results**
- Logs **Monitoring Events**
- Logs **Security Alerts** when rules are triggered.

### Stack
- **PostgreSQL** — official database backend.
- **SQLAlchemy 2.x** (async) with `asyncpg` driver.
- **Alembic** — schema migrations.

### Configuration

Copie `.env.example` para `.env`. Para usar o banco, gere **duas senhas diferentes**
e preencha `POSTGRES_PASSWORD` (administração) e `NETSENTINEL_DB_PASSWORD` (aplicação).
O Compose recusa iniciar quando alguma senha está vazia; não existe senha padrão.

Preencha também as URLs correspondentes (os valores abaixo são placeholders):

```env
DATABASE_URL=postgresql+asyncpg://netsentinel_app:<senha-app-url-encoded>@127.0.0.1:5432/netsentinel
MIGRATION_DATABASE_URL=postgresql+asyncpg://netsentinel:<senha-admin-url-encoded>@127.0.0.1:5432/netsentinel
```

Use percent-encoding para caracteres especiais nas senhas das URLs. Nunca versione `.env`.
Para executar somente `scan`/`monitor` sem banco, deixe as URLs vazias.

Em volumes novos, `docker/postgres/010-runtime-role.sql` cria `netsentinel_app`
sem privilégios administrativos, com leitura/inserção/atualização e uso de sequências.
As migrations usam `MIGRATION_DATABASE_URL`; por compatibilidade, na ausência dela,
Alembic usa `DATABASE_URL` (nesse caso o usuário precisa ser dono do schema).

#### Alert severity configuration (v0.4.0)

NetSentinel permite configurar a severidade atribuída às regras de detecção de alertas de segurança através de variáveis de ambiente ou no arquivo `.env`.

| Variável | Regra | Valor Padrão | Valores Aceitos |
| :--- | :--- | :--- | :--- |
| `ALERT_SEVERITY_NEW_OPEN_PORT` | Porta aberta detectada (`NEW_OPEN_PORT`) | `HIGH` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ALERT_SEVERITY_PORT_CLOSED` | Porta fechada detectada (`PORT_CLOSED`) | `LOW` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ALERT_SEVERITY_HOST_DOWN` | Host inacessível (`HOST_DOWN`) | `MEDIUM` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ALERT_SEVERITY_HOST_RECOVERED` | Host recuperado (`HOST_RECOVERED`) | `INFO` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ALERT_SEVERITY_EXPECTED_OPEN_PORT` | Porta esperada aberta (`EXPECTED_OPEN_PORT`) | `INFO` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ALERT_SEVERITY_UNEXPECTED_OPEN_PORT` | Porta inesperada aberta (`UNEXPECTED_OPEN_PORT`) | `HIGH` | `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |

Os valores são insensíveis a maiúsculas e minúsculas (ex: `medium`, `Medium`, `MEDIUM`). Valores inválidos impedem o início do monitoramento com mensagem explicativa e código de saída 1.

#### Expected TCP Ports Policy (v0.4.0)

O NetSentinel permite definir uma política de baseline de portas TCP esperadas através da variável `EXPECTED_TCP_PORTS`:

```env
EXPECTED_TCP_PORTS=22,80,443
```

- **Apenas classificação**: esta configuração **NÃO** altera as portas escaneadas. O parâmetro `--ports` continua definindo estritamente o que será monitorado na rede.
- **Porta esperada aberta**: quando uma porta contida na lista transiciona de `CLOSED` para `OPEN`, é gerado o alerta `EXPECTED_OPEN_PORT` (severidade padrão: `INFO`).
- **Porta inesperada aberta**: quando uma porta não listada transiciona de `CLOSED` para `OPEN`, é gerado o alerta `UNEXPECTED_OPEN_PORT` (severidade padrão: `HIGH`).
- **Política desabilitada**: se `EXPECTED_TCP_PORTS` estiver vazia ou não definida, o comportamento legado permanece ativo (`PORT_OPENED` gera `NEW_OPEN_PORT`).
- **Não obrigatória**: portas esperadas não geram alerta se permanecerem fechadas.



### Local Development Environment (Docker Compose)

To spin up a local PostgreSQL instance for development:

A porta é publicada somente em `127.0.0.1:5432`. Não a exponha na rede ou na Internet.

```bash
# Start the database in the background
docker compose up -d db

# Stop the database
docker compose down

# Stop the database and remove local data
docker compose down -v
```

### Applying migrations

Once a PostgreSQL instance is available:

```bash
alembic upgrade head
```

Após as migrations, use `netsentinel monitor 127.0.0.1 --ports 80,443 --persist`.
`scan` e `monitor` sem `--persist` continuam funcionando sem banco configurado.

### Atualização de volumes existentes — sem apagar dados

Alterar `.env` **não troca a senha de um banco já inicializado**, e scripts em
`docker-entrypoint-initdb.d` só executam automaticamente em volumes vazios.
Não use `docker compose down -v` para aplicar esta correção: isso apaga o volume.

1. Faça backup. Se a senha antiga foi utilizada com a porta exposta, trate-a como
   comprometida e rotacione-a na instância existente. Em uma sessão administrativa
   `psql`, use `\password netsentinel` para trocar a senha sem colocá-la em comandos SQL
   ou no histórico do terminal. Atualize `POSTGRES_PASSWORD` e `MIGRATION_DATABASE_URL`.
2. Configure uma senha diferente em `NETSENTINEL_DB_PASSWORD` e recrie **somente o
   container**, preservando o volume, para aplicar o bind local e a montagem do script:
   `docker compose up -d --force-recreate db`.
3. Se o papel `netsentinel_app` ainda não existe, execute uma vez como administrador:
   `docker compose exec db psql -U netsentinel -d netsentinel -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/010-runtime-role.sql`.
   O script concede permissões nas tabelas existentes e nas futuras migrations do
   proprietário `netsentinel`. Se o papel já existe, não repita `CREATE ROLE`:
   revise suas permissões e use `\password netsentinel_app` caso precise rotacionar a senha.
4. Aponte `DATABASE_URL` para `netsentinel_app` e execute as migrations com a
   credencial administrativa. Não utilize o superusuário na aplicação.

Esses passos são manuais e não são executados pela aplicação nem pelos testes unitários.

## Limitações atuais (v0.6.0)

A v0.6.0 ainda NÃO possui:
- Outros canais externos além de Webhook HTTP POST (ex.: email nativo SMTP, Slack direto, Teams);
- Supressão ou agrupamento temporal automático de alertas (alert throttling/deduplication);
- Dashboard web ou interface frontend (planejado para versões futuras);
- Reabertura (reopen) ou atribuição de analistas via CLI;
- Suporte a ICMP ping nativo ou probes UDP;
- Autodiscovery de redes ou varredura de sub-redes inteiras;
- Detecção de versões de serviço (service/OS fingerprinting);
- Scanners de vulnerabilidade ou módulos de exploração;
- E não é um IDS/IPS completo com inspeção profunda de pacotes (DPI).

## Desenvolvimento

Comandos de rotina e validação (requer dependências de `[dev]`):

```bash
# Linter
ruff check .

# Formatter
ruff format --check .

# Type checking
mypy app

# Unit tests (no database required)
pytest

# PostgreSQL integration tests (requires Docker Compose database)
# First time: create the test database manually in psql:
#   CREATE DATABASE netsentinel_test;
#   GRANT ALL PRIVILEGES ON DATABASE netsentinel_test TO netsentinel;
TEST_DATABASE_URL=postgresql+asyncpg://netsentinel:<senha-admin-url-encoded>@127.0.0.1:5432/netsentinel_test pytest -m integration
```

## REST API

O NetSentinel v0.7.0 expõe seus serviços de monitoramento, histórico e triagem através de uma API HTTP REST assíncrona versionada (`/api/v1`), sem duplicar regras de negócio da CLI.

### Inicialização do Servidor

Para iniciar o servidor FastAPI localmente:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

A documentação interativa estará acessível em:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

### Política de Autenticação e Segurança

- **Header de Autenticação**: `X-API-Key` (chaves passadas como query parameter são expressamente rejeitadas).
- **Sem chave configurada (`API_KEY` vazia)**: Modo de desenvolvimento local. Endpoints de leitura são públicos; mutações (`acknowledge` / `resolve`) retornam `503 Service Unavailable` (`MUTATIONS_DISABLED`).
- **Com chave configurada (`API_KEY` definida)**: Todos os endpoints (leitura e mutação) exigem o header `X-API-Key` válido. Requisições sem a chave ou com chave incorreta recebem `401 Unauthorized` com mensagem genérica (comparação constant-time via `secrets.compare_digest`).
- **Probes de Health**: `GET /health`, `GET /api/v1/health/live` e `GET /api/v1/health/ready` são sempre públicos para orquestradores e balanceadores.
- **CORS Estrito e Opt-in**: Desabilitado por padrão. Habilitado exclusivamente via `API_CORS_ORIGINS` com origens explícitas separadas por vírgula (ex: `http://localhost:3000,http://127.0.0.1:8080`). O uso de wildcard `*` é estritamente proibido.
- **Sanitização de Segredos**: Credenciais, connection strings e tokens nunca são expostos em respostas de erro, schemas ou logs.

### Tabela de Endpoints

| Método | Endpoint | Autenticação | Descrição |
|---|---|---|---|
| `GET` | `/health` | Pública | Endpoint legado de health (`{"status": "ok", "service": "netsentinel"}`). |
| `GET` | `/api/v1/health/live` | Pública | Liveness probe (indica que a aplicação está rodando; sem I/O de banco). |
| `GET` | `/api/v1/health/ready` | Pública | Readiness probe (valida conectividade `SELECT 1` com o PostgreSQL; 503 se indisponível). |
| `GET` | `/api/v1/dashboard/summary` | `X-API-Key` | Resumo agregado de métricas operacionais para o dashboard (hosts, scans, alertas por status/severidade). |
| `GET` | `/api/v1/hosts` | `X-API-Key` | Lista hosts monitorados com paginação (`limit`, `offset`), filtro `enabled` e busca textual (`q`). |
| `GET` | `/api/v1/hosts/{target}/history` | `X-API-Key` | Histórico de scans do host especificado (alvo validado via `NetworkTarget`). |
| `GET` | `/api/v1/scans` | `X-API-Key` | Listagem global paginada de scans (`limit`, `offset`) com filtro opcional por alvo (`target`). |
| `GET` | `/api/v1/scans/{scan_id}` | `X-API-Key` | Detalhes de um scan específico, incluindo portas sondadas, eventos e alertas gerados. |
| `GET` | `/api/v1/alerts/summary` | `X-API-Key` | Métricas agregadas de alertas no banco via SQL (`total`, `by_status`, `by_severity`). |
| `GET` | `/api/v1/alerts` | `X-API-Key` | Fila de alertas com paginação e filtros combinados (`status`, `severity`, `type`, `target`). |
| `GET` | `/api/v1/alerts/{alert_id}` | `X-API-Key` | Detalhes completos de um alerta de segurança específico. |
| `GET` | `/api/v1/alerts/{alert_id}/deliveries` | `X-API-Key` | Histórico sanitizado de tentativas de entrega de notificações para o alerta. |
| `POST` | `/api/v1/alerts/{alert_id}/acknowledge` | `X-API-Key` | Triagem remota: transiciona o alerta para `ACKNOWLEDGED` (409 em transições inválidas). |
| `POST` | `/api/v1/alerts/{alert_id}/resolve` | `X-API-Key` | Triagem remota: transiciona o alerta para `RESOLVED` (409 em transições inválidas). |

### Exemplos com cURL

**1. Verificar Liveness e Readiness:**
```bash
curl -s http://127.0.0.1:8000/api/v1/health/live
curl -s http://127.0.0.1:8000/api/v1/health/ready
```

**2. Obter Resumo do Dashboard:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  http://127.0.0.1:8000/api/v1/dashboard/summary
```

**3. Listar Hosts com Busca Textual:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  "http://127.0.0.1:8000/api/v1/hosts?q=local&limit=10&offset=0"
```

**4. Listar Scans Globais:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  "http://127.0.0.1:8000/api/v1/scans?limit=10&offset=0"
```

**5. Obter Histórico de um Alvo:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  "http://127.0.0.1:8000/api/v1/hosts/127.0.0.1/history?limit=5"
```

**6. Obter Resumo Agregado de Alertas:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  http://127.0.0.1:8000/api/v1/alerts/summary
```

**7. Filtrar Alertas Abertos de Alta Severidade:**
```bash
curl -s -H "X-API-Key: sua-chave-aqui" \
  "http://127.0.0.1:8000/api/v1/alerts?status=OPEN&severity=HIGH&limit=20"
```

**8. Reconhecer e Resolver um Alerta Remotamente:**
```bash
# Reconhecer (Acknowledge)
curl -s -X POST -H "X-API-Key: sua-chave-aqui" \
  http://127.0.0.1:8000/api/v1/alerts/42/acknowledge

# Resolver (Resolve)
curl -s -X POST -H "X-API-Key: sua-chave-aqui" \
  http://127.0.0.1:8000/api/v1/alerts/42/resolve
```

## Web Dashboard

O **NetSentinel Web Dashboard** é uma interface web moderna, responsiva e defensiva para SOC e observabilidade de redes, construída com React 18, TypeScript strict, Vite, React Router 6 e TanStack Query 5.

### Stack Técnica do Frontend

- **Core & Runtime**: React 18, TypeScript em modo `strict`, Vite como bundler ultrarrápido.
- **Roteamento**: React Router 6 com rotas aninhadas e fallback 404.
- **Server State & Cache**: TanStack Query (React Query v5) para cache determinístico, auto-refetch, polling inteligente e invalidação atômica após mutações.
- **Visualização de Dados**: Recharts para gráficos de distribuição por status e severidade com suporte a acessibilidade e legendas textuais.
- **Design System & Estilo**: Tokens CSS customizados (variáveis CSS), Flexbox/Grid modernos, suporte nativo a temas `dark`, `light` e `system` com persistência em `localStorage`.
- **Ícones**: Lucide React.
- **Containerização**: Multi-stage build com Node 20 para compilação estática e Nginx 1.27 Alpine para servir assets de produção com proxy reverso same-origin.

### Fluxo de Páginas e Telas

1. **Overview (`/`)**:
   - Cards com indicadores consolidados: total de hosts monitorados, scans executados, alertas abertos, reconhecidos, resolvidos e de alta criticidade.
   - Gráficos acessíveis: distribuição de alertas por status (Bar Chart) e por severidade (Pie Chart ordenado logicamente: INFO -> CRITICAL).
   - Tabelas resumidas com os 5 alertas mais recentes e os 5 últimos scans globais.
   - Indicador de status operacional (Health & Readiness) em tempo real da API e do banco PostgreSQL.
2. **Alerts (`/alerts`)**:
   - Tabela defensiva com badges textuais para status (`OPEN`, `ACKNOWLEDGED`, `RESOLVED`) e severidade (`INFO` a `CRITICAL`).
   - Filtros dinâmicos sincronizados bidirecionalmente com a query string da URL: status, severidade, alvo (`target`) e tipo de alerta (`type`).
   - Paginação server-side com limites configuráveis (20, 50, 100).
   - Ações rápidas de triagem direta ou navegação para detalhes.
3. **Alert Details (`/alerts/:alertId`)**:
   - Metadados completos do alerta: ID, severidade, tipo, status, alvo, porta, mensagem e datas de ciclo de vida (`created_at`, `acknowledged_at`, `resolved_at`).
   - Ações de triagem seguras via modal: `Acknowledge` e `Resolve` com validação de estado, desabilitação de botões contra duplo clique e tratamento resiliente de conflitos concorrentes (HTTP 409).
   - Seção de histórico de entregas de notificações (`deliveries`) com status de envio, tentativas, timestamps e mensagens de erro sanitizadas (sem expor segredos nem URLs de webhook).
4. **Hosts (`/hosts`)**:
   - Catálogo de alvos monitorados com filtros por status (`enabled`) e busca textual server-side (`q`) por endereço IP ou hostname.
   - Paginação e navegação com 1 clique para o histórico do host.
5. **Host Details (`/hosts/:target`)**:
   - Histórico cronológico de scans realizados para o alvo informado (`GET /api/v1/hosts/{target}/history`), exibindo ID, tempo de resposta, timestamps e links para o scan individual.
6. **Scans (`/scans`)**:
   - Visão global paginada de todos os scans registrados no sistema com filtro por alvo.
7. **Scan Details (`/scans/:scanId`)**:
   - Inspeção aprofundada organizada em seções:
     - **Overview**: Alvo, status de disponibilidade, tempo de resposta (ms), início e término.
     - **Ports**: Tabela de resultados por porta sondada com status e latência.
     - **Monitoring Events**: Linha do tempo de eventos de monitoramento detectados (`PORT_OPENED`, `HOST_BECAME_AVAILABLE`, etc.).
     - **Security Alerts**: Alertas de segurança gerados durante o scan com links diretos para a página de cada alerta.
8. **Settings (`/settings`)**:
   - Painel de conexão com a API: teste de conectividade em tempo real para verificar liveness e credenciais.
   - Gerenciamento de API Key em runtime: campo protegido com opção de mostrar/ocultar senha, armazenamento volátil em memória por padrão ou opcional em `sessionStorage` para a aba ativa, e botão `Clear API Key` para remoção instantânea.
   - Preferências de tema: alternância imediata entre `system`, `light` e `dark`.
   - Intervalo de polling configurável: `Off`, `5s`, `10s`, `30s`, `60s` (padrão: `10s`). Pausa automática quando a aba do navegador fica em segundo plano.

### Desenvolvimento Local

Para desenvolver localmente com hot-reload no frontend e backend:

**Terminal 1 — Backend FastAPI:**
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — Frontend Vite:**
```bash
cd frontend
npm install
npm run dev
```

O servidor de desenvolvimento do Vite iniciará em `http://127.0.0.1:5173`. As requisições direcionadas para `/api/` são automaticamente encaminhadas via proxy interno do Vite para `http://127.0.0.1:8000`, evitando problemas de CORS durante o desenvolvimento.

### Execução em Produção com Docker Compose

A stack completa de produção pode ser inicializada através do Docker Compose utilizando o profile `web`:

```bash
docker compose --profile web up --build -d
```

O Compose cria o volume de dados automaticamente na primeira execução e reutiliza
`projeto_netsentinel_netsentinel_postgres_data` quando ele já existe. Para usar outro
volume, defina `NETSENTINEL_POSTGRES_VOLUME` no ambiente ou no `.env` antes de iniciar.
O volume é gerenciado pelo Compose: `docker compose down -v` remove seus dados.

Serviços iniciados:
- `db`: PostgreSQL 16 com persistência em volume seguro (`port 5432`).
- `api`: Container FastAPI executando o backend em Python 3.12 (`port 8000`).
- `dashboard`: Container Nginx Alpine servindo a aplicação compilada e atuando como proxy reverso same-origin (`port 3000`).

Acesse a interface no navegador:
```text
http://127.0.0.1:3000
```

Todas as chamadas para `/api/v1/*` no navegador utilizam a mesma origem (`same-origin`), sendo roteadas transparentemente pelo Nginx para o backend FastAPI. O Nginx também possui fallback SPA (`try_files $uri $uri/ /index.html`), garantindo que rotas diretas (ex: `http://127.0.0.1:3000/alerts`) funcionem sem erro 404.

### Gerenciamento de Autenticação e API Key

- **Ausência de Segredos Embutidos**: Nenhuma chave de API é gravada no código-fonte, variáveis `VITE_*` ou imagem Docker. Não existe variável `VITE_API_KEY`.
- **Fornecimento em Runtime**: O operador insere a API Key no menu **Settings** ou no aviso de autenticação da aplicação.
- **Armazenamento Seguro no Cliente**:
  - Por padrão, a chave reside estritamente no estado em memória da aplicação React.
  - Caso o operador marque "Remember for this browser tab", ela é guardada temporariamente no `sessionStorage` (destruído ao fechar a aba).
  - A chave **nunca** é gravada no `localStorage` nem enviada via query parameters na URL.
  - A limpeza da chave via `Clear API Key` apaga imediatamente o estado em memória e limpa o `sessionStorage`.
- **Comunicação Segura**: O client HTTP central injeta a chave no cabeçalho padronizado `X-API-Key`.
- **Prevenção XSS**: Toda informação exibida pela interface (mensagens de erro, alvos, nomes de hosts) é renderizada com escape padrão do React, com uso estritamente vetado de `dangerouslySetInnerHTML`.

### Recomendações de Segurança para Produção

A autenticação por API Key única e comunicação HTTP local são projetadas para laboratórios, testes e redes defensivas controladas. Para publicação em ambientes corporativos ou expostos:
- Utilize terminação TLS/HTTPS em proxy reverso (Nginx, Caddy ou Cloudflare).
- Configure certificados digitais válidos e force cabeçalhos HSTS (`Strict-Transport-Security`).
- Considere a evolução para provedores de identidade centralizados (OIDC/OAuth2/SAML) e políticas de RBAC (Role-Based Access Control).

## Roadmap
 
A **v0.4.0** consolidou o motor de alertas de segurança (`Alert Engine`), regras de detecção de mudanças de porta e host, severidades configuráveis, política de baseline com `EXPECTED_TCP_PORTS` e persistência integrada ao histórico.

A **v0.5.0** introduz o ciclo de vida e triagem de alertas (`AlertStatus`, `AlertLifecycle`, persistência de status e timestamps no PostgreSQL, `AlertTriageService`, fila de alertas na CLI com subcomandos `acknowledge` e `resolve`, e filtros `--status` e `--severity`).

A **v0.6.0** introduz o subsistema completo de notificações e entrega de alertas de segurança em tempo real:

- **Política de severidade configurável (`NotificationPolicy`)**: Define o threshold mínimo para geração de notificações com base na severidade do alerta (`NOTIFICATION_MIN_SEVERITY`, default `HIGH`). Valores aceitos (case-insensitive): `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- **Provedor assíncrono Webhook (`WebhookNotificationSender`)**: Disparo de requisições HTTP POST usando `httpx.AsyncClient` com payload JSON padronizado, sanitização de caracteres ANSI/controle, validação de URL e mascaramento de parâmetros sensíveis.
- **Auditoria e persistência relacional (`notification_deliveries`)**: Registro transacional no PostgreSQL de cada tentativa de entrega (`channel`, `success`, `status_code`, `error_message`, `delivered_at`) vinculado ao `SecurityAlertRecord` com integridade referencial `ON DELETE CASCADE`.
- **Serviço orquestrador (`NotificationDeliveryService`)**: Unifica filtragem por política, despacho assíncrono para senders registrados e persistência atômica no banco de dados.
- **Integração no monitoramento contínuo (`netsentinel monitor`)**:
  - Com `--persist`: Os alertas gerados no ciclo são persistidos no PostgreSQL e, em seguida, avaliados e despachados via webhooks com gravação transacional das tentativas em `notification_deliveries`.
  - Sem `--persist` (in-memory): O monitoramento mantém isolamento total de banco de dados e realiza a entrega via webhook em memória, caso `NOTIFICATION_WEBHOOK_URL` esteja configurada.

A **v0.7.0** introduz a API HTTP REST versionada (`/api/v1`) construída com FastAPI e Pydantic v2:
- **Endpoints RESTful padronizados**: Probes de liveness/readiness, hosts, histórico, scans detalhados, resumo estatístico agregado de alertas (`/summary`), fila de alertas com múltiplos filtros combinados e histórico de entregas de notificações.
- **Triagem remota de alertas**: Ações remotas de `acknowledge` e `resolve` que operam diretamente através do `AlertTriageService`, garantindo validação de transições idêntica à da CLI.
- **Segurança**: Autenticação centralizada via header `X-API-Key`, bloqueio de mutações em ambientes locais sem chave configurada (`MUTATIONS_DISABLED`), comparação segura em tempo constante (`secrets.compare_digest`) e CORS estrito e opt-in sem suporte a wildcards.
- **Documentação e Schema OpenAPI**: OpenAPI e Swagger UI totalmente integrados sem vazamento de segredos nos schemas gerados.

```env
# Política de severidade mínima (default: HIGH)
NOTIFICATION_MIN_SEVERITY=HIGH

# Endpoint HTTP POST para disparo de webhooks (desabilitado se vazio)
NOTIFICATION_WEBHOOK_URL=https://webhook.site/seu-endpoint
NOTIFICATION_WEBHOOK_TIMEOUT=5.0
```

Exemplo de execução com persistência e notificações:
```bash
netsentinel monitor 127.0.0.1 --ports 22,80,443 --persist
```

A **v0.8.0** introduz o Web Dashboard moderno para operação defensiva:
- **Interface Web em React + TypeScript**: Dashboard completo para SOC e observabilidade com páginas Overview, Alerts, Alert Details, Hosts, Host Details, Scans, Scan Details e Settings.
- **Visualização Operacional e Triagem**: Métricas gráficas de status e severidade com Recharts, filtros avançados na fila de alertas com sincronização na URL, e ações de triagem (`acknowledge` e `resolve`) com confirmação modal e proteção contra concorrência (HTTP 409).
- **Extensões de API no Backend**: Endpoint global `GET /api/v1/scans` com paginação e filtro por alvo via `ScanQueryService`, agregação analítica `GET /api/v1/dashboard/summary` via `DashboardQueryService` e busca textual server-side `q` em `GET /api/v1/hosts`.
- **Autenticação Segura em Runtime**: Operação com API Key informada em tempo de execução, mantida em memória (ou `sessionStorage` opcional para a aba), cabeçalho `X-API-Key` estrito, sem chaves no build (`VITE_API_KEY`) e ausência de `localStorage` para credenciais.
- **Empacotamento e Entrega com Docker**: Multi-stage build Nginx Alpine para frontend estático com headers de segurança, fallback SPA e proxy reverso same-origin para `/api/`, integrados ao Docker Compose via profile `web`.

## Uso responsável

O NetSentinel deve ser utilizado estritamente em:
- Sistemas próprios.
- `localhost` e laboratórios locais.
- CTFs autorizados.
- Redes onde exista autorização prévia e explícita.

Não utilize a ferramenta contra infraestruturas públicas sem autorização.

## Licença

Projeto desenvolvido para fins educacionais.
