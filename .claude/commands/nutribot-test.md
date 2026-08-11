Você é um engenheiro de qualidade especializado no projeto NutriBot. Sua tarefa é gerar ou revisar testes para o componente indicado nos argumentos.

**Passo 1 — Leia o contexto necessário:**
- `docs/architecture.md` seção 4 (estrutura de diretórios e responsabilidades dos services)
- `docs/api-spec.md` seção 3 (contratos internos dos services)
- `docs/fuzzy-match.md` (se for testar NutritionService)
- `tests/fixtures/golden_meals.json` se existir

Se o arquivo sendo testado já existir, leia-o antes de gerar testes.

**Passo 2 — Identifique a tarefa pelo argumento ($ARGUMENTS):**

Se o argumento mencionar **um service ou arquivo específico** (ex: "NutritionService", "conversation.py"):
- Gere testes unitários pytest (async com pytest-asyncio quando necessário)
- Cubra: caminho feliz, edge cases, falhas de dependências externas (mock de OpenAI, mock de DB)
- Siga este padrão:
  ```python
  # tests/test_[nome].py
  import pytest
  from unittest.mock import AsyncMock, patch
  from app.services.[nome] import [NomeService]

  class Test[NomeService]:
      @pytest.fixture
      def service(self):
          return [NomeService]()

      async def test_[caso_feliz](self, service):
          ...

      async def test_[edge_case](self, service):
          ...

      async def test_[falha_externa](self, service):
          ...
  ```
- Meta: cobertura > 80% do service

Se o argumento for **"golden-dataset"**:
- Leia `tests/fixtures/golden_meals.json` se existir
- Proponha 10 novos casos de teste para adicionar, cobrindo:
  - Comidas regionais brasileiras ainda não cobertas
  - Gírias e nomes populares
  - Erros de digitação comuns
  - Pratos compostos complexos
- Formato JSON: `{"input": "...", "expected_foods": [...], "expected_calories_range": [min, max]}`

Se o argumento for **"webhook [telegram|whatsapp|payment]"**:
- Gere testes de integração para o webhook indicado
- Use `httpx.AsyncClient` com `TestClient` do FastAPI
- Cubra: payload válido, assinatura inválida, payload malformado, modo manutenção ativo

Se o argumento for **"state-machine"**:
- Gere testes para todas as transições de estado em `docs/NutriBot_PRD_v2.1.md` seção 7
- Para cada estado: testa transição válida, transição inválida, timeout

**Regras gerais:**
- Testes devem ser determinísticos — mock todas as chamadas externas (OpenAI, Telegram, DB)
- Nomes de teste em snake_case descritivo: `test_fuzzy_match_returns_taco_entry_for_common_food`
- Não testar o GPT em si — apenas a lógica que usa o output do GPT (use fixtures)
- Sempre incluir o caso de falha da API externa (simular timeout, 429, 500)

$ARGUMENTS
