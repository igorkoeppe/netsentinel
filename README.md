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

## Arquitetura

```text
       CLI
        │
        ▼
  NetworkTarget
        │
        ▼
   Port Scanner
        │
        ▼
    TCP Probe
        │
        ▼
     Network

       ---

 Port Scan Results
        │
        ▼
Availability Analysis
        │
        ▼
AVAILABLE / UNAVAILABLE
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

## Limitações atuais (v0.4.0)

A v0.4.0 ainda NÃO possui:
- Sistema de notificações externas (email, Slack, Webhooks, etc.);
- Reconhecimento (acknowledgement) ou supressão/agrupamento temporal de alertas;
- Dashboard web ou interface frontend;
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

## Roadmap
 
A **v0.4.0** consolidou o motor de alertas de segurança (`Alert Engine`), regras de detecção de mudanças de porta e host, severidades configuráveis, política de baseline com `EXPECTED_TCP_PORTS` e persistência integrada ao histórico.
 
Versões futuras explorarão API REST com FastAPI, descoberta avançada de serviços e dashboard web para visualização gráfica. 

## Uso responsável

O NetSentinel deve ser utilizado estritamente em:
- Sistemas próprios.
- `localhost` e laboratórios locais.
- CTFs autorizados.
- Redes onde exista autorização prévia e explícita.

Não utilize a ferramenta contra infraestruturas públicas sem autorização.

## Licença

Projeto desenvolvido para fins educacionais.
