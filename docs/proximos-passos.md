# Nouri — Próximos Passos

**Atualizado:** Outubro 2026  
**Estado atual:** Pré-prod local Docker · 62% cobertura · brand "Nouri" aplicada

---

## Imediato — antes de ir para produção

| # | Tarefa | Responsável | Notas |
|---|--------|-------------|-------|
| 1 | **Deploy do site atualizado para VPS** | Dev | `./scripts/deploy.sh --build` na VPS. O `website/index.html` tem FAQ, testimonials, planos e remoção de WhatsApp. |
| 2 | **Gerar icon-192.png e icon-512.png** | Dev | `marketing/icon.svg` está correto. Converter para PNG (cairosvg ou online) e substituir `app/static/icon-192.png` e `icon-512.png` para atualizar o PWA. |
| 3 | **Atualizar foto de perfil do bot no Telegram** | Produto | Usar `marketing/profile.svg` (ou PNG gerado). Feito via BotFather: `/setuserpic`. |
| 4 | **Confirmar username do bot** | Produto | O site e templates usam `@NouriNutriBot`. Se o username real ainda for `@NutriBotOficialBot`, atualizar os links em `app/templates/` e `website/index.html`. |

---

## Curto prazo — 1 a 2 semanas

### Qualidade e testes
- [ ] Cobertura está em **62.25%** (threshold 55% ✅). Meta: chegar a **65%** antes da Fase 3.
  - Priorizar `app/services/report.py` (geração PDF) e `app/routers/reports.py`
  - `app/services/scheduler.py` — jobs de alerta
- [ ] Adicionar teste de integração end-to-end para o fluxo de onboarding completo (cadastro → configuração → primeiro registro)

### Produto
- [ ] **Histórico de peso** — PRD já existe em `docs/prd-historico-peso.md`. Feature esperada pelos usuários; estimativa: 3–4 dias de dev.
- [ ] **Depoimentos reais no site** — as 3 citações em `website/index.html` são placeholder. Coletar feedback de usuários beta e substituir.
- [ ] **Preços finais** — os valores em `#planos` (Básico R$19,90 / Premium R$39,90 / Nutricionista R$99,90) precisam de validação de produto antes do lançamento público.

### Infra
- [ ] Renovação automática SSL via cron no host (certbot renew). Verificar se o cron está configurado no VPS.
- [ ] Backup automático do PostgreSQL — volume Docker não tem snapshot externo configurado.

---

## Médio prazo — Fase 3

### Definição de escopo (pendente decisão)

| Opção | Prós | Contras |
|-------|------|---------|
| **PWA** (melhorar dashboard atual) | Zero novo stack, deploy já existe, funciona offline | Limitações de notificação push no iOS |
| **React Native** | App nativo iOS + Android, melhor UX mobile | Novo stack, 2+ meses para MVP |
| **Flutter** | Único codebase, Web + iOS + Android | Time precisa aprender Flutter |

**Recomendação:** Começar com PWA (melhorar o dashboard atual para ser instalável e offline-capable) — menor risco, maior velocidade.

### Backlog Fase 3

- [ ] Notificações push via PWA (Web Push API)
- [ ] Modo offline — service worker + IndexedDB para cache de refeições
- [ ] Gráficos de macros semanais (Chart.js no dashboard)
- [ ] Scanner de código de barras (câmera → lookup TACO/TBCA)
- [ ] Integração com balanças Bluetooth (Web Bluetooth API)

---

## Melhoria contínua

### Performance
- [ ] **Cache Redis** para sessões de conversação (reduzir reads no PostgreSQL por mensagem)
- [ ] **Otimização de prompts** — revisar `docs/prompts.md` com `/claude-api prompt-audit` para reduzir tokens gastos por request
- [ ] **Pool de conexões DB** — atual `pool_size=3` em `app/db/session.py`; avaliar aumento para produção com mais usuários

### Analytics
- [ ] Configurar dashboards no PostHog para:
  - Funil de onboarding (cadastro → primeiro registro → 7 dias ativos)
  - Churn rate por plano
  - Alimentos mais registrados (top 50)
- [ ] Revisar eventos rastreados em `app/services/analytics.py`

### Segurança
- [ ] Auditoria de dependências: `pip-audit` no CI/CD
- [ ] Renovar `JWT_SECRET` e `RAW_INPUT_ENCRYPTION_KEY` periodicamente (recomendado a cada 6 meses)
- [ ] CSP: revisar cabeçalhos em `app/main.py` após deploy com o site novo (inline scripts do Tailwind CDN podem conflitar)

---

## Documentação — pendências

| Arquivo | Status | O que fazer |
|---------|--------|-------------|
| `docs/NutriBot_PRD_v2.1.md` | ⚠️ Parcial | Ainda usa "NutriBot" no título e em seções internas; WhatsApp ainda aparece em jornadas de usuário |
| `docs/prompts.md` | ⚠️ Desatualizado | Referencia GPT-4o — atualizar para Claude Haiku 4.5 (texto) e Sonnet 4.6 (visão) |
| `docs/api-spec.md` | ⚠️ Verificar | Rotas admin e B2B adicionadas em sprints posteriores podem não estar documentadas |
| `docs/fuzzy-match.md` | ✅ OK | Algoritmo de lookup está correto |
| `docs/admin-panel.md` | ✅ OK | Atualizado em Admin-1 |
| `docs/prd-historico-peso.md` | ✅ OK | Aguardando implementação |

---

## Log de decisões relevantes

| Data | Decisão | Motivo |
|------|---------|--------|
| Out 2026 | WhatsApp removido permanentemente | API Evolution muito instável; custo de manutenção > benefício |
| Out 2026 | Render + Neon → VPS + Docker | Custos, controle e latência; free tier Neon limitante |
| Out 2026 | Modelo freemium removido | CAC alto para usuários gratuitos; conversão baixa |
| Out 2026 | Brand "NutriBot" → "Nouri" | Diferenciação de mercado; nome mais limpo e memorável |
| Out 2026 | `conversation.py` → pacote `/conversation/` | Arquivo com 2.631 linhas se tornava inviável de manter |
