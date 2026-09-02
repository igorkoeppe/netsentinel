# NetSentinel — Project Specification

## 1. Visão Geral

**NetSentinel** é um sistema de monitoramento de redes com foco em observabilidade e segurança.

O objetivo do projeto é monitorar hosts e serviços de uma rede, registrar histórico de disponibilidade e portas abertas, detectar mudanças relevantes e gerar alertas de segurança.

O projeto será desenvolvido inicialmente como uma aplicação 100% em software, sem depender de hardware adicional.

---

## 2. Objetivos

### Objetivo principal

Construir uma plataforma capaz de:

- monitorar hosts;
- verificar disponibilidade;
- medir latência;
- identificar portas TCP abertas;
- armazenar histórico de verificações;
- detectar alterações no estado da rede;
- gerar alertas;
- disponibilizar os dados via API;
- exibir informações em um dashboard web.

### Objetivos de aprendizagem

O projeto deve servir como portfólio técnico e explorar conhecimentos de:

- Python;
- redes de computadores;
- programação assíncrona;
- APIs REST;
- bancos de dados;
- Docker;
- testes automatizados;
- CI/CD;
- observabilidade;
- fundamentos de cybersecurity;
- arquitetura de software.

---

## 3. Escopo

### Dentro do escopo

- cadastro de hosts;
- descoberta de disponibilidade;
- medição de latência;
- TCP port scan controlado;
- monitoramento periódico;
- histórico de scans;
- detecção de novas portas abertas;
- detecção de portas fechadas;
- detecção de host offline;
- geração de alertas;
- API REST;
- dashboard;
- execução com Docker Compose;
- testes automatizados;
- pipeline de CI.

### Fora do escopo inicial

- exploração de vulnerabilidades;
- execução de exploits;
- brute force;
- evasão de mecanismos de segurança;
- scanning de redes sem autorização;
- resposta automática ofensiva;
- malware analysis;
- packet injection;
- IDS completo baseado em inspeção profunda de pacotes.

Esses itens poderão ser estudados futuramente apenas em ambientes próprios, laboratórios ou cenários explicitamente autorizados.

---

## 4. Arquitetura Inicial

```text
┌──────────────────────┐
│ Monitoring Workers   │
│ Python + asyncio     │
│                      │
│ ICMP / TCP / DNS     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Monitoring Service   │
│ FastAPI              │
└──────────┬───────────┘
           │
     ┌─────┴───────────────┐
     ▼                     ▼
┌──────────────┐     ┌──────────────┐
│ PostgreSQL   │     │ Alert Engine │
│              │     │              │
│ hosts        │     │ regras       │
│ scans        │     │ severidade   │
│ ports        │     │ eventos      │
│ alerts       │     │              │
└──────┬───────┘     └──────────────┘
       │
       ▼
┌──────────────────────┐
│ REST API / WebSocket │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Dashboard Web        │
│ React / Next.js      │
└──────────────────────┘
```

---

## 5. Stack

### Backend

- Python 3.12+
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- asyncio
- PostgreSQL

### Monitoramento

Inicialmente utilizar recursos nativos ou bibliotecas simples:

- `asyncio`;
- `socket`;
- `subprocess`;
- `ipaddress`.

Integrações futuras podem incluir:

- Nmap;
- Scapy;
- psutil.

### Frontend

Planejado para versões posteriores:

- React ou Next.js;
- TypeScript;
- biblioteca de gráficos a definir.

### Infraestrutura

- Docker;
- Docker Compose;
- GitHub Actions.

### Qualidade

- pytest;
- Ruff;
- mypy;
- coverage.

---

## 6. Estrutura Inicial do Repositório

```text
netsentinel/
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── api/
│   │   └── routes/
│   │
│   ├── core/
│   │   ├── config.py
│   │   └── logging.py
│   │
│   ├── monitoring/
│   │   ├── ping.py
│   │   ├── port_scanner.py
│   │   └── scheduler.py
│   │
│   ├── detection/
│   │   ├── engine.py
│   │   └── rules.py
│   │
│   ├── models/
│   │
│   ├── schemas/
│   │
│   ├── repositories/
│   │
│   └── services/
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── migrations/
├── docs/
│
├── .github/
│   └── workflows/
│
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── README.md
├── project.md
└── claude.md
```

---

## 7. Modelo de Dados Inicial

### Host

```text
id
name
address
enabled
created_at
updated_at
```

### Scan

```text
id
host_id
status
latency_ms
started_at
finished_at
```

### Port

```text
id
scan_id
port
protocol
state
service
```

### Alert

```text
id
host_id
type
severity
message
created_at
resolved_at
```

---

## 8. Regras de Detecção

### Host offline

Gerar alerta quando um host anteriormente disponível deixar de responder.

Severidade sugerida:

`MEDIUM`

### Nova porta aberta

Comparar o scan atual com o último estado conhecido.

Exemplo:

```text
Antes:
22, 80, 443

Depois:
22, 80, 443, 4444
```

Gerar alerta:

```text
type: NEW_OPEN_PORT
severity: HIGH
```

### Porta fechada

Quando uma porta previamente aberta deixar de responder.

Severidade sugerida:

`LOW` ou `MEDIUM`

### Latência elevada

Gerar alerta quando a latência ultrapassar um limite configurável.

Severidade sugerida:

`LOW`

---

## 9. API Inicial

### Hosts

```http
GET /hosts
GET /hosts/{id}
POST /hosts
PATCH /hosts/{id}
DELETE /hosts/{id}
```

### Monitoring

```http
POST /hosts/{id}/scan
GET /hosts/{id}/scans
GET /hosts/{id}/ports
```

### Alerts

```http
GET /alerts
GET /alerts/{id}
PATCH /alerts/{id}/resolve
```

### Health check

```http
GET /health
```

---

## 10. Roadmap

### v0.1 — Network Scanner (completed)

Objetivo:

criar o primeiro núcleo funcional do NetSentinel.

Features:

- validação de IPv4/IPv6/hostname;
- teste de disponibilidade;
- medição de latência;
- TCP port scanner;
- CLI básica;
- testes unitários.

### v0.2 — Monitoramento contínuo (completed)

- execução assíncrona;
- intervalos configuráveis;
- change detection (snapshot comparison);
- in-memory tracking;
- eventos em tempo real;
- session summary.

### v0.3 — Persistence & History (in development)

- PostgreSQL;
- SQLAlchemy 2.x (async) + asyncpg;
- Alembic migrations;
- modelos ORM: hosts, scans, port_results, monitoring_events;
- configuração de DATABASE_URL;
- infraestrutura de persistência (sem integração com monitor ainda).

### v0.4 — Integração Persistence + Monitor

- PostgreSQL;
- SQLAlchemy;
- migrations;
- histórico de scans;
- histórico de portas.

### v0.5 — Detection Engine

- comparação entre scans;
- host offline;
- nova porta aberta;
- porta fechada;
- latência elevada;
- severidades.

### v0.6 — Dashboard

- visão geral;
- hosts online/offline;
- alertas recentes;
- histórico;
- gráficos.

### v0.7 — Containers

- Dockerfile;
- Docker Compose;
- backend;
- banco;
- frontend.

### v0.8 — Qualidade

- pytest;
- coverage;
- Ruff;
- mypy;
- GitHub Actions.

### v1.0 — Release inicial

- documentação;
- arquitetura revisada;
- screenshots;
- exemplos;
- configuração segura;
- tag de release.

---

## 11. Princípios do Projeto

### Simplicidade primeiro

Não adicionar complexidade antes de existir uma necessidade concreta.

### Evolução incremental

Cada versão deve produzir algo executável e demonstrável.

### Segurança por padrão

Nunca assumir que o usuário possui autorização para monitorar redes de terceiros.

O projeto deve ser utilizado apenas em:

- redes próprias;
- laboratórios;
- máquinas virtuais;
- CTFs autorizados;
- ambientes onde exista autorização explícita.

### Código testável

A lógica de negócio deve ser separada de:

- rede;
- banco;
- framework web;
- sistema operacional.

Isso permite testes unitários sem depender de infraestrutura externa.

---

## 12. Convenções de Código

### Python

- type hints obrigatórios em código novo;
- funções pequenas;
- nomes descritivos;
- evitar funções com múltiplas responsabilidades;
- preferir composição a herança;
- tratar exceções explicitamente;
- evitar `except Exception` sem justificativa.

### Formatação

Utilizar:

```bash
ruff check .
ruff format .
mypy app
pytest
```

### Commits

Utilizar Conventional Commits.

Exemplos:

```text
feat: add asynchronous tcp port scanner
fix: handle unreachable hosts correctly
test: add scanner timeout tests
refactor: isolate host monitoring service
docs: document detection rules
ci: add github actions workflow
```

---

## 13. Critérios para Pull Requests

Uma mudança deve:

- possuir objetivo claro;
- manter compatibilidade com o escopo atual;
- incluir testes quando aplicável;
- não introduzir dependências desnecessárias;
- não reduzir a cobertura sem justificativa;
- passar no lint;
- passar nos testes;
- manter código legível.

---

## 14. Segurança e Uso Responsável

O NetSentinel é uma ferramenta educacional e defensiva.

Nenhuma funcionalidade deve ser criada com o objetivo de:

- comprometer sistemas;
- explorar vulnerabilidades;
- obter acesso não autorizado;
- ocultar atividade maliciosa;
- executar ações destrutivas.

Funcionalidades de scanning devem ser projetadas para ambientes autorizados e com limites razoáveis de concorrência, timeout e taxa de requisições.

---

## 15. Definição de Sucesso

A primeira versão estável deverá permitir que um usuário execute:

```bash
docker compose up
```

cadastre hosts autorizados e visualize:

- status;
- latência;
- portas;
- histórico;
- alertas de mudança.

O repositório deverá demonstrar domínio de redes, backend, arquitetura de software, testes, containers e fundamentos de segurança defensiva.
