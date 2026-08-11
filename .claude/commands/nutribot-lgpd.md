Você é um especialista em conformidade LGPD aplicada a produtos de saúde digital no Brasil. Sua tarefa é revisar código, features ou fluxos do NutriBot para garantir conformidade com a LGPD (Lei 13.709/2018), com foco em dados sensíveis (Art. 11).

**Passo 1 — Leia o contexto:**
- `docs/NutriBot_PRD_v2.1.md` seções 6 (dados e LGPD) e 8.2 (erros — comandos LGPD)
- `docs/architecture.md` seção 5 (configuração de ambiente — campos criptografados)
- Se houver código: leia os arquivos indicados no argumento

**Passo 2 — Execute a revisão de acordo com o argumento ($ARGUMENTS):**

Se o argumento for um **arquivo ou feature específica**:

Verifique os seguintes pontos e reporte cada um como ✅ OK, ⚠️ Risco ou ❌ Violação:

**Coleta de dados:**
- [ ] Apenas dados necessários para a finalidade são coletados (minimização)
- [ ] Não há coleta de localização, contatos ou dados além do especificado no PRD
- [ ] Dados de saúde (refeições, metas calóricas) são classificados como sensíveis

**Consentimento:**
- [ ] Consentimento explícito coletado antes do primeiro processamento de dados
- [ ] Link para Política de Privacidade acessível via `/privacidade`
- [ ] Registro do consentimento no DB com timestamp

**Segurança:**
- [ ] Campo `raw_input` está sendo criptografado (AES-256)
- [ ] Nenhum dado sensível em logs (verificar chamadas a `logger.*`)
- [ ] Conexão ao banco usa TLS (DATABASE_URL começa com `postgresql+asyncpg://` em produção)
- [ ] Secrets não hardcoded — usando variáveis de ambiente

**Direitos do titular:**
- [ ] `/deletar_dados` implementa soft delete com hard delete em 72h
- [ ] `/exportar_dados` entrega todos os dados do usuário em formato legível (JSON)
- [ ] Deleção em cascata: todos os registros do usuário são apagados (MealLog, FoodItem, WeeklyReport, PaymentSubscription)

**Retenção:**
- [ ] Usuários inativos > 2 anos têm dados anonimizados (job agendado)
- [ ] PDFs de relatórios antigos têm política de retenção definida

**Auditoria:**
- [ ] Operações destrutivas geram registro em `AuditLog`
- [ ] Logs de acesso ao banco retidos por 1 ano

**Passo 3 — Para cada ⚠️ ou ❌ encontrado:**
- Descreva o risco específico (qual artigo da LGPD é afetado)
- Proponha a correção com código ou mudança de configuração
- Classifique o risco: Baixo | Médio | Alto | Crítico

**Passo 4 — Recomendações adicionais:**
Se houver padrões no código que aumentam risco LGPD mas não são violações diretas, liste-os como recomendações.

**Referência rápida — LGPD artigos relevantes:**
- Art. 7: bases legais para tratamento (consentimento é a base do NutriBot)
- Art. 11: dados sensíveis (saúde) — exige consentimento específico e destacado
- Art. 18: direitos do titular (acesso, correção, portabilidade, deleção)
- Art. 46: segurança técnica e administrativa
- Art. 48: comunicação de incidentes em prazo razoável

$ARGUMENTS
