Carregue o contexto completo do projeto NutriBot lendo os seguintes arquivos na ordem indicada e internalize as informações antes de responder qualquer pergunta sobre o projeto:

1. Leia `CLAUDE.md` — stack técnica, comandos de desenvolvimento, estrutura de diretórios planejada
2. Leia `docs/NutriBot_PRD_v2.1.md` — requisitos, personas, jornadas, MoSCoW, modelo de negócio, LGPD, cronograma, métricas
3. Leia `docs/architecture.md` — diagramas de sequência, ADRs, estrutura de diretórios, deploy
4. Leia `docs/prompts.md` — system prompts do GPT-4o, schemas de resposta, estratégia de cache
5. Leia `docs/api-spec.md` — endpoints, contratos internos dos services, schemas Pydantic
6. Leia `docs/fuzzy-match.md` — algoritmo de lookup TACO/USDA, pipeline de normalização, benchmarks

Após ler todos os arquivos, responda com um resumo estruturado de 5 pontos confirmando que você entendeu:
1. O que o NutriBot faz e para quem
2. O stack técnico do MVP (linguagem, banco, IA, canais)
3. A feature mais crítica do Sprint 1 (além da infra)
4. A maior restrição legal do projeto
5. A principal vantagem competitiva defensável

Se algum arquivo não existir ainda (projeto pré-código), informe e continue com os arquivos disponíveis.

$ARGUMENTS
