# Claude Development Guide — NetSentinel

Este arquivo define como um agente de código deve trabalhar no projeto **NetSentinel**.

Leia também `project.md` antes de realizar alterações relevantes.

---

## 1. Missão

Ajudar a desenvolver o NetSentinel de maneira incremental, segura, legível e profissional.

O objetivo não é produzir o máximo de código possível.

O objetivo é criar um projeto de portfólio que demonstre:

- fundamentos sólidos;
- boas decisões de arquitetura;
- conhecimento de redes;
- segurança defensiva;
- testes;
- documentação;
- evolução clara do projeto.

---

## 2. Regra Principal

Antes de implementar uma funcionalidade:

1. entenda o objetivo;
2. consulte `project.md`;
3. identifique a menor mudança necessária;
4. preserve a arquitetura existente;
5. implemente;
6. adicione ou atualize testes;
7. execute validações;
8. explique resumidamente o que mudou.

Não faça grandes refatorações não solicitadas.

---

## 3. Escopo de Segurança

O NetSentinel é um projeto educacional e defensivo.

O agente pode ajudar com funcionalidades de:

- monitoramento;
- descoberta de disponibilidade;
- scans TCP limitados;
- inventário de serviços;
- alertas;
- observabilidade;
- análise de mudanças;
- laboratórios próprios;
- testes em localhost, containers e redes privadas autorizadas.

Não transformar o projeto em ferramenta para:

- exploração automática;
- brute force;
- credential stuffing;
- evasão;
- persistência;
- exfiltração;
- malware;
- DDoS;
- acesso não autorizado;
- scanning agressivo de redes públicas.

Ao implementar scanners, utilizar defaults conservadores.

Exemplos:

- timeout configurável;
- concorrência limitada;
- intervalos configuráveis;
- nenhuma varredura automática de grandes ranges;
- nenhum alvo público adicionado por padrão.

---

## 4. Stack Oficial

Salvo decisão explícita em contrário, utilizar:

### Backend

- Python 3.12+
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- PostgreSQL

### Tooling

- pytest
- Ruff
- mypy
- coverage

### Infraestrutura

- Docker
- Docker Compose
- GitHub Actions

Não adicionar uma biblioteca quando a standard library resolver o problema de forma clara.

---

## 5. Arquitetura

As responsabilidades devem permanecer separadas.

```text
API
 ↓
Services
 ↓
Repositories
 ↓
Database
```

O monitoramento segue:

```text
Monitoring
   ↓
Scan Result
   ↓
Detection Engine
   ↓
Alerts
```

### `api/`

Responsável apenas por:

- HTTP;
- validação de entrada;
- status codes;
- serialização;
- chamada dos services.

Evitar lógica de negócio nas rotas.

### `services/`

Responsável por casos de uso.

Exemplos:

- cadastrar host;
- iniciar scan;
- consultar histórico;
- resolver alerta.

### `monitoring/`

Responsável pela interação com rede.

Exemplos:

- ping;
- TCP connect;
- port scan;
- resolução DNS.

### `detection/`

Responsável por analisar resultados.

Não deve executar scans diretamente.

Exemplo:

```text
previous_scan + current_scan
              ↓
       detection engine
              ↓
            alerts
```

### `repositories/`

Responsável pelo acesso aos dados.

Services não devem conhecer detalhes desnecessários do ORM.

---

## 6. Princípios de Implementação

### Faça

- código pequeno e legível;
- type hints;
- dataclasses ou modelos claros quando apropriado;
- funções puras para lógica de detecção;
- dependency injection quando simplificar testes;
- tratamento explícito de erros;
- interfaces pequenas;
- testes determinísticos.

### Evite

- abstrações prematuras;
- classes gigantes;
- singletons;
- estado global;
- lógica de negócio em endpoints;
- lógica de negócio em modelos ORM;
- dependências circulares;
- `print()` para logging;
- `except Exception: pass`;
- números mágicos.

---

## 7. Programação Assíncrona

Utilizar `asyncio` apenas quando houver ganho real em operações de I/O.

Para scans concorrentes:

- utilizar limite de concorrência;
- evitar criar milhares de tasks sem controle;
- usar `asyncio.Semaphore` quando necessário;
- definir timeout;
- garantir cleanup.

Exemplo conceitual:

```python
semaphore = asyncio.Semaphore(max_concurrency)
```

Não otimizar prematuramente.

Primeiro obter comportamento correto e testável.

---

## 8. Port Scanner

O scanner inicial deve utilizar conexão TCP.

Objetivo:

```text
tentar conexão
     ↓
sucesso → OPEN
falha   → CLOSED / UNREACHABLE
```

O scanner deve possuir:

- host;
- lista explícita de portas;
- timeout;
- limite de concorrência.

Não fazer scan de `1-65535` por padrão.

Uma lista inicial aceitável para demonstração pode incluir:

```text
22
53
80
443
3306
5432
6379
8080
```

O usuário pode alterar a configuração.

---

## 9. Detection Engine

A lógica de detecção deve preferencialmente ser pura.

Exemplo:

```python
alerts = detect_changes(previous_scan, current_scan)
```

Isso facilita testes.

Regras iniciais:

### NEW_OPEN_PORT

Se:

```text
current_open_ports - previous_open_ports
```

não for vazio.

### CLOSED_PORT

Se:

```text
previous_open_ports - current_open_ports
```

não for vazio.

### HOST_OFFLINE

Se:

```text
previous.status == ONLINE
current.status == OFFLINE
```

### HIGH_LATENCY

Se a latência ultrapassar o threshold configurado.

---

## 10. Severidades

Utilizar:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Evitar classificar eventos triviais como `CRITICAL`.

Defaults sugeridos:

```text
HOST_OFFLINE     → MEDIUM
NEW_OPEN_PORT    → HIGH
CLOSED_PORT      → LOW
HIGH_LATENCY     → LOW
```

Esses valores devem poder evoluir.

---

## 11. Testes

Toda lógica relevante deve ser testada.

### Unit tests

Prioridade para:

- validação de hosts;
- scanner;
- parsing;
- detection engine;
- services.

### Integration tests

Utilizar para:

- API;
- banco;
- repositories.

### Evitar nos testes unitários

- acesso real à internet;
- hosts públicos;
- dependência de serviços externos;
- sleeps longos;
- portas aleatórias não controladas.

Preferir mocks, fixtures ou servidores locais de teste.

---

## 12. Testes do Scanner

Casos importantes:

```text
porta aberta
porta fechada
timeout
host inválido
DNS inválido
lista vazia
concorrência
cancelamento
```

Sempre que possível, criar um servidor TCP local durante o teste.

---

## 13. Logging

Não utilizar `print()` em código de produção.

Preferir o módulo `logging`.

Logs devem fornecer contexto útil.

Exemplo:

```text
host
port
operation
duration
result
```

Não registrar:

- senhas;
- tokens;
- secrets;
- credenciais;
- conteúdo sensível desnecessário.

---

## 14. Configuração

Configurações devem vir de:

1. valores default seguros;
2. variáveis de ambiente;
3. arquivo `.env` apenas em desenvolvimento.

Nunca commitar `.env`.

Manter `.env.example`.

Exemplos de configuração:

```text
DATABASE_URL
SCAN_TIMEOUT
SCAN_MAX_CONCURRENCY
MONITOR_INTERVAL
LOG_LEVEL
```

---

## 15. Banco de Dados

Usar migrations com Alembic.

Não modificar schema de produção somente com `create_all`.

Models principais:

```text
Host
Scan
Port
Alert
```

Relacionamentos devem ser explícitos.

Evitar armazenar dados duplicados quando não houver benefício claro.

---

## 16. API

Seguir convenções REST.

Respostas de erro devem ser consistentes.

Exemplos:

```text
200 OK
201 Created
204 No Content
400 Bad Request
404 Not Found
409 Conflict
422 Validation Error
```

Nunca retornar stack trace ao cliente.

---

## 17. FastAPI

Rotas devem ser pequenas.

Exemplo ideal:

```python
@router.post("/hosts")
async def create_host(
    payload: HostCreate,
    service: HostService = Depends(get_host_service),
):
    return await service.create(payload)
```

Evitar colocar:

- queries SQL;
- scanner;
- regras de detecção;

diretamente no endpoint.

---

## 18. Dependências

Antes de adicionar uma dependência:

1. verificar se ela já existe;
2. avaliar se é realmente necessária;
3. verificar se Python standard library resolve;
4. considerar impacto de manutenção.

Nunca adicionar frameworks grandes para resolver problemas pequenos.

---

## 19. Qualidade

Antes de considerar uma tarefa concluída, executar quando disponível:

```bash
ruff check .
ruff format --check .
mypy app
pytest
```

Para alterações relevantes:

```bash
pytest --cov=app
```

Se algum comando não puder ser executado, informar claramente.

---

## 20. Commits

Quando sugerir commits, usar Conventional Commits.

Exemplos:

```text
feat: add tcp port scanner
feat: implement host monitoring service
fix: handle scan timeout correctly
test: cover port change detection
refactor: separate scanner from detection engine
docs: update project roadmap
ci: add backend test workflow
```

Evitar commits vagos como:

```text
update files
changes
fix stuff
```

---

## 21. Pull Requests

Uma PR deve responder:

```text
O que mudou?
Por que mudou?
Como foi testado?
Existe algum impacto de segurança?
```

Preferir PRs pequenas.

---

## 22. README

Ao adicionar funcionalidades visíveis para o usuário, avaliar se `README.md` também precisa ser atualizado.

O README final deve conter:

- descrição;
- arquitetura;
- instalação;
- quick start;
- screenshots;
- endpoints;
- exemplos;
- roadmap;
- segurança;
- licença.

---

## 23. Documentação

`project.md` representa a direção funcional e arquitetural do projeto.

Se uma decisão estrutural importante mudar, atualizar `project.md`.

Não deixar documentação contradizer o código.

---

## 24. Desenvolvimento Incremental

Não tentar implementar o roadmap inteiro de uma vez.

Prioridade atual:

```text
v0.1 — Network Scanner
```

Ordem recomendada:

```text
1. estrutura Python
2. configuração
3. validação de host
4. teste de disponibilidade
5. TCP port scanner
6. modelos de resultado
7. CLI simples
8. unit tests
9. lint/type checking
10. CI
```

Somente depois avançar para monitoramento contínuo.

---

## 25. Critério de Conclusão de Tarefa

Uma funcionalidade está concluída quando:

- funciona;
- possui código legível;
- possui type hints;
- erros relevantes são tratados;
- testes foram adicionados;
- testes existentes continuam passando;
- lint passa;
- documentação foi atualizada quando necessário.

---

## 26. Comportamento Esperado do Agente

Ao receber uma nova tarefa:

### Primeiro

Inspecione os arquivos relevantes.

### Depois

Explique brevemente o que pretende alterar.

### Durante

Faça a menor alteração coerente possível.

### Ao terminar

Informe:

```text
Arquivos alterados
Resumo das mudanças
Testes executados
Possíveis próximos passos
```

Não alegue que testes passaram se eles não foram executados.

---

## 27. Não Fazer Automaticamente

Sem solicitação explícita, não:

- alterar toda a arquitetura;
- trocar frameworks;
- atualizar todas as dependências;
- reformatar o repositório inteiro;
- renomear grandes conjuntos de arquivos;
- adicionar Kubernetes;
- adicionar microservices;
- adicionar Redis;
- adicionar Celery;
- adicionar autenticação complexa;
- adicionar machine learning.

Essas tecnologias só devem entrar quando houver uma justificativa real.

---

## 28. Filosofia

O NetSentinel deve parecer um projeto construído por um engenheiro que entende por que cada componente existe.

Preferir:

```text
simples
testável
observável
seguro
incremental
```

em vez de:

```text
complexo
superabstraído
cheio de tecnologias
difícil de explicar
```

Cada decisão técnica deve ser defensável em uma entrevista.
