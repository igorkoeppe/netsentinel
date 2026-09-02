# NetSentinel

Uma ferramenta educacional e defensiva de monitoramento e análise de conectividade TCP, desenvolvida como projeto de Engenharia da Computação com foco em cybersecurity.

## Features

- Validação rigorosa de alvos (IPv4, IPv6 e hostnames).
- Probes TCP assíncronos de alta performance.
- Scanner concorrente de múltiplas portas com limite controlável.
- Detecção de disponibilidade do host via TCP (inferência por portas `OPEN` ou `CLOSED`).
- Medição de tempo de resposta baseada no TCP handshake.
- CLI amigável (`netsentinel`).
- Camada de persistência transacional com PostgreSQL (v0.3.0 em desenvolvimento).
  > Nota: A gravação automática dos dados a partir do `netsentinel monitor` ainda não está ativada.

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

Você pode consultar o histórico de monitoramento persistido de um host específico. Os dados incluem informações sobre o status de disponibilidade do host, detalhes sobre portas verificadas e eventos de estado ao longo do tempo.

> **Nota:** A consulta de histórico requer o PostgreSQL rodando (por exemplo, via `docker compose up -d db`), a variável `DATABASE_URL` configurada, e as migrations aplicadas (`alembic upgrade head`).

Para visualizar os scans mais recentes de um host:

```bash
netsentinel history 192.168.1.5
```

Por padrão, os 10 scans mais recentes são exibidos. Você pode modificar esse limite utilizando a flag `--limit`:

```bash
netsentinel history 192.168.1.5 --limit 5
```

Para inspecionar um scan específico e visualizar as informações de portas testadas e os eventos de mudança detectados:

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
scan -> snapshot -> wait -> scan -> snapshot -> compare -> events
```

O primeiro snapshot apenas estabelece o baseline da sessão em memória, não gerando falsos positivos ou eventos artificiais. A partir do segundo snapshot, o motor passa a detectar as seguintes **mudanças observadas entre snapshots consecutivos**:

- `PORT_OPENED`
- `PORT_CLOSED`
- `HOST_BECAME_AVAILABLE`
- `HOST_BECAME_UNAVAILABLE`

Esses eventos representam alterações concretas no estado e não são varreduras de vulnerabilidade e não funcionam como um IDS completo.

O comando irá executar indefinitamente ou até atingir o limite estipulado em `--count`. Se interrompido manualmente pelo usuário com `Ctrl+C` ou finalizado naturalmente, um resumo da sessão é exibido informando a quantidade de snapshots realizados, eventos detectados consolidados por tipo, e a duração.

> **IMPORTANTE**: Monitoring events in v0.2.0 are stored only in memory and are discarded when the process exits. Os resultados ainda não são persistidos.

## Como funciona

### Detecção de estado da porta
- **OPEN**: Conexão TCP estabelecida com sucesso.
- **CLOSED**: O host respondeu recusando a conexão (`ConnectionRefusedError`). Isso significa que a máquina está ativa, mas o serviço está inativo ou protegido, o que ainda é prova de disponibilidade.
- **TIMEOUT / UNREACHABLE**: Sem resposta clara ou bloqueio silencioso por firewall.

### Disponibilidade TCP
> Na v0.1, disponibilidade e tempo de resposta são inferidos através de conexões TCP. O NetSentinel ainda não implementa ICMP ping.

Se ao menos uma porta retornar `OPEN` ou `CLOSED`, o host é considerado `AVAILABLE`. O tempo de resposta será o menor tempo entre os probes respondidos.

## Persistence layer (v0.3 — in development)

NetSentinel v0.3 introduces the database schema and migration infrastructure required for persistent monitoring history.

### Stack
- **PostgreSQL** — official database backend.
- **SQLAlchemy 2.x** (async) with `asyncpg` driver.
- **Alembic** — schema migrations.

### Configuration

Add to your `.env` (see `.env.example`):

```env
DATABASE_URL=postgresql+asyncpg://netsentinel:netsentinel@localhost:5432/netsentinel
```

### Local Development Environment (Docker Compose)

To spin up a local PostgreSQL instance for development:

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

> **Important:** Automatic persistence of monitoring sessions is **not enabled yet**.
> `netsentinel scan` and `netsentinel monitor` continue to work without a database configured.

## Limitações atuais (v0.2.0)

A v0.2.0 ainda NÃO possui:
- PostgreSQL ou persistência em banco de dados;
- Buscas históricas (historical queries);
- Geração de alertas com severidade (alert severity);
- Sistema de notificações (email, Slack, etc);
- Dashboard web ou frontend;
- Suporte a ICMP (ping) ou UDP;
- Autodiscovery de hosts ou ranges como 1-65535;
- Service fingerprinting;
- Scanners de vulnerabilidade (vulnerability scanning);
- E não é um IDS (Intrusion Detection System) completo.

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
TEST_DATABASE_URL=postgresql+asyncpg://netsentinel:netsentinel@localhost:5432/netsentinel_test pytest -m integration
```

## Roadmap

Versões futuras implementarão banco de dados SQL (via SQLAlchemy/Alembic) para histórico das execuções e, futuramente, descoberta ICMP nativa e API FastAPI para painel de controle. 

## Uso responsável

O NetSentinel deve ser utilizado estritamente em:
- Sistemas próprios.
- `localhost` e laboratórios locais.
- CTFs autorizados.
- Redes onde exista autorização prévia e explícita.

Não utilize a ferramenta contra infraestruturas públicas sem autorização.

## Licença

Projeto desenvolvido para fins educacionais.
