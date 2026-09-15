# PRD — Histórico de Peso

**Produto:** NutriBot  
**Versão:** 1.0  
**Data:** 2026-09-15  
**Status:** Planejado — implementação futura  
**Autor:** Equipe NutriBot

---

## 1. Visão Geral

Adicionar rastreamento periódico do peso corporal ao NutriBot, fechando o ciclo entre ingestão alimentar (já rastreada) e desfecho corporal (atualmente ausente). O dado de peso é o que responde à pergunta central do usuário: "minha dieta está funcionando?"

## 2. Problema

O NutriBot rastreia calorias, macros, fibra e água com alta fidelidade, mas não registra o resultado desse esforço. Usuários ficam sem feedback de progresso e têm menor motivação para manutenção do hábito de registro. Nutricionistas no painel B2B não conseguem acompanhar evolução ponderal do paciente sem ferramentas externas.

## 3. Objetivos

### 3.1 Objetivos (in scope)
- Registrar peso corporal com data, em todos os canais (bot, dashboard, WhatsApp)
- Visualizar evolução em gráfico de linha com média móvel de 7 dias
- Incluir gráfico de peso no relatório PDF semanal/mensal
- Expor histórico de peso do paciente no painel do nutricionista

### 3.2 Não-objetivos (out of scope)
- Percentual de gordura corporal ou IMC derivado de composição
- Integração com balanças inteligentes (Withings, Garmin)
- Prescrição de metas de peso (responsabilidade do nutricionista, não do app)
- Notificações automáticas de pesagem (evitar pressão psicológica)
- Dietas ou planos de emagrecimento gerados por IA

## 4. Usuários-alvo

| Persona | Necessidade |
|---|---|
| Paciente (usuário final) | Ver se está progredindo em relação ao peso; registrar facilmente |
| Nutricionista | Monitorar evolução ponderal do paciente entre consultas |

## 5. User Stories

### Paciente
- Como paciente, quero registrar meu peso pelo bot digitando "pessei 73.5kg" para não precisar abrir o painel
- Como paciente, quero ver um gráfico de evolução do meu peso no dashboard para entender minha tendência
- Como paciente, quero editar ou excluir um registro de peso que inseri errado
- Como paciente, quero que meu peso apareça no relatório PDF que compartilho com meu nutricionista

### Nutricionista
- Como nutricionista, quero ver o histórico de peso de cada paciente no painel para não precisar anotar em separado
- Como nutricionista, quero ver a correlação entre aderência calórica e variação de peso do paciente

## 6. Requisitos Funcionais

### Fase 1 — Registro e Visualização (MVP)

| ID | Requisito | Prioridade |
|---|---|---|
| PF-01 | Comando `/peso [kg]` no bot: registra peso, confirma com emoji de progresso | Must |
| PF-02 | Detecção natural: "pessei 73kg", "meu peso é 68.5", "74 quilos hoje" | Must |
| PF-03 | Entrada manual no dashboard: campo de peso na seção "Resumo de hoje" | Must |
| PF-04 | Card de evolução no dashboard: gráfico de linha últimos 30 registros | Must |
| PF-05 | CRUD completo: editar e excluir registros de peso no painel histórico | Must |
| PF-06 | Bloqueio de datas futuras e validação de range (20–300 kg) | Must |
| PF-07 | Exibição de último peso registrado + variação desde o registro anterior | Should |

### Fase 2 — B2B e Relatórios

| ID | Requisito | Prioridade |
|---|---|---|
| PF-08 | Histórico de peso do paciente no painel do nutricionista | Must |
| PF-09 | Gráfico de peso no relatório PDF (seção nova: "Evolução Ponderal") | Must |
| PF-10 | Correlação visual: peso vs aderência calórica no mesmo período | Should |
| PF-11 | Nutricionista pode inserir peso retroativo do paciente pelo painel | Should |

### Fase 3 — Inteligência (opcional)

| ID | Requisito | Prioridade |
|---|---|---|
| PF-12 | Média móvel de 7 dias no gráfico (suaviza oscilação diária) | Should |
| PF-13 | Atualização automática do TDEE quando variação de peso > 2 kg | Could |
| PF-14 | Projeção de tendência (com disclaimer claro de estimativa) | Could |

## 7. Requisitos Não-funcionais

- Dados de peso classificados como **dados sensíveis LGPD** (saúde) — mesma proteção dos logs de refeição
- Linguagem neutra em toda a UI: sem termos como "emagrecer", "engordar", "meta de perda"
- Gráfico deve suportar séries esparsas graciosamente (≥ 2 pontos para exibir linha)
- Não haverá notificações/alertas automáticos de "você não pesou essa semana"

## 8. Especificação Técnica

### 8.1 Modelo de dados

```sql
CREATE TABLE weight_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    logged_at   TIMESTAMPTZ NOT NULL,
    weight_kg   NUMERIC(5,2) NOT NULL CHECK (weight_kg BETWEEN 20 AND 300),
    notes       TEXT,                    -- opcional, ex: "pós academia"
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_weight_logs_user_date ON weight_logs(user_id, logged_at DESC);
```

DDL adicionado via `_apply_pending_ddl()` em `app/main.py` (padrão já existente).

### 8.2 Endpoints REST

```
POST   /api/peso              { weight_kg, logged_date? }  → { id, weight_kg, delta_kg, logged_at }
GET    /api/peso/historico    ?days=30                     → [{ id, weight_kg, logged_at, delta_kg }]
PATCH  /api/peso/{id}         { weight_kg }                → { weight_kg, delta_kg }
DELETE /api/peso/{id}                                      → 204
```

### 8.3 Parsing no bot

```python
# Regex prioritária — padrão: "pessei 73.5kg", "74 quilos", "peso: 68"
_WEIGHT_PATTERN = re.compile(
    r"pes(?:ei|sei|o|ando|ar)[\s:]*(\d{2,3}[.,]?\d{0,2})\s*(?:kg|quilos?|k\b)?",
    re.IGNORECASE
)
# Fallback — "meu peso é 73.5", "73.5 kg hoje"
_WEIGHT_FALLBACK = re.compile(r"\b(\d{2,3}[.,]\d{1,2})\s*kg\b", re.IGNORECASE)
```

Detecção em `_is_weight_message()` → `_log_weight_and_reply()`, mesmo padrão da água.

### 8.4 Arquivos a modificar

| Arquivo | Mudança |
|---|---|
| `app/models/weight_log.py` | Novo modelo SQLAlchemy |
| `app/main.py` | DDL + `_apply_pending_ddl()` |
| `app/routers/dashboard.py` | 4 rotas REST + queries |
| `app/services/conversation.py` | `_is_weight_message`, `_parse_weight_kg`, `_cmd_peso`, IDLE handler |
| `app/templates/dashboard.html` | Card + gráfico de peso |
| `app/templates/historico.html` | Tile peso no grid + CRUD inline |
| `data/report_template.html` | Seção "Evolução Ponderal" no PDF |
| `tests/test_conversation.py` | Testes de parsing e comando |

## 9. UX e Diretrizes de Produto

### Linguagem
- ✅ "seu peso hoje", "evolução do peso", "último registro"
- ✅ "variação de -0.8 kg esta semana"
- ❌ "você engordou", "meta de emagrecimento", "precisa perder"

### Gráfico
- Exibir pontos reais + linha suavizada (média móvel 7 dias quando ≥ 7 pontos)
- Eixo Y com escala ajustada ao range do usuário (não começa em zero)
- Tooltip no hover: data, peso, variação desde anterior

### Frequência de registro
- Sem obrigatoriedade, sem lembretes automáticos
- Sugestão passiva na tela: "Pesquise sempre pela manhã, em jejum, para comparações mais precisas"

## 10. Métricas de Sucesso

| Métrica | Meta (90 dias após lançamento) |
|---|---|
| Adoção (% usuários com ≥ 1 registro de peso) | > 40% |
| Frequência de registro | Mediana ≥ 2 registros/semana entre adotantes |
| Retenção 30 dias vs controle | +8% entre usuários que usam peso |
| NPS pós-feature | ≥ +5 pontos vs baseline |

## 11. Estimativa de Esforço

| Componente | Estimativa |
|---|---|
| Modelo + DDL + rotas REST | 2h |
| Parsing bot + comandos | 3h |
| Dashboard card + gráfico | 4h |
| Histórico painel (CRUD) | 3h |
| Painel nutricionista | 3h |
| Relatório PDF | 2h |
| Testes | 3h |
| **Total** | **~20h** |

## 12. Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| UX prejudicial para usuários com transtornos alimentares | Média | Alto | Linguagem neutra, sem gamificação, sem pressão de meta |
| Séries esparsas que confundem mais do que ajudam | Alta | Médio | Gráfico só exibe linha com ≥ 2 pontos; média móvel com ≥ 7 |
| Interpretação incorreta de oscilações diárias | Alta | Baixo | Tooltip educativo + sugestão de horário consistente |
| Fronteira médica (prescrição vs registro) | Baixa | Alto | Produto é registro + visualização apenas; nutricionista define metas fora do app |

## 13. Questões em Aberto

1. O nutricionista poderá definir uma "meta de peso" para o paciente visível no app? (fronteira clínica a definir)
2. Incluir campo `notes` opcional ("pós academia", "pós menstruação") no registro?
3. Exibir IMC calculado automaticamente? (simples tecnicamente, mas pode ser contraproducente)
4. Fase 3 (projeção de tendência) requer validação clínica antes de ativar?

---

*Próximo passo: aprovação do escopo da Fase 1 para inclusão no planejamento de sprint.*
