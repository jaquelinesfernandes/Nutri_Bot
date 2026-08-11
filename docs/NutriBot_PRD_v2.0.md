# NutriBot — Product Requirements Document v2.0

**Status:** Draft para Revisão  
**Versão:** 2.0 (revisão PM/negócios sobre v1.0)  
**Data:** Junho 2026  
**Responsável:** Produto

---

## Nota do Revisor (PM)

Esta versão incorpora o escopo original da v1.0 e adiciona: análise de produto, posicionamento competitivo, jornadas de usuário, priorização MoSCoW, modelo de negócio refinado, métricas AARRR e sugestões estratégicas. Itens marcados com `⚑ Sugestão PM` são adições ou alterações em relação à v1.0.

---

## 1. Visão do Produto

### 1.1 Tipo de Produto

NutriBot é um **assistente de saúde conversacional B2C com potencial B2B**, operando no modelo **SaaS Freemium** com distribuição via canais de mensageria (WhatsApp e Telegram). Combina três categorias:

| Categoria | Descrição |
|-----------|-----------|
| **Conversational AI** | Registro e consulta em linguagem natural, sem formulários |
| **Health & Wellness SaaS** | Tracking nutricional com meta, histórico e insights |
| **B2B Tool** | Plataforma para nutricionistas acompanharem pacientes |

**Natureza dos dados:** Dados de saúde sensíveis (LGPD Art. 11). O produto lida com comportamento alimentar, peso e metas — o que exige rigor em privacidade e tom empático nas comunicações.

**Modelo de crescimento:** Principalmente *product-led growth* (PLG) via engajamento diário + *word-of-mouth* (WOM) impulsionado pelo relatório semanal compartilhável. Baixo CAC esperado pela distribuição via WhatsApp (sem fricção de instalação de app).

### 1.2 Posicionamento

> **Para** adultos brasileiros entre 18–45 anos que tentam controlar a alimentação mas abandonam diários por falta de praticidade, **o NutriBot** é o único assistente nutricional que funciona dentro do WhatsApp, sem instalar nada, registrando refeições em segundos por texto, foto ou voz **— diferente de** apps como MyFitnessPal que exigem instalação, cadastro complexo e busca manual de alimentos.

### 1.3 Por que Agora

- WhatsApp é usado por 97% dos smartphones ativos no Brasil (Statista 2024)
- GPT-4o tornou viável o processamento de texto+foto+áudio em um único modelo a custo acessível
- Mercado de saúde digital BR estimado em R$ 4,2 bi (2025), com lacuna clara em ferramentas conversacionais
- LGPD em maturidade — janela para construir confiança antes de grandes players replicarem

---

## 2. Contexto e Problema

### 2.1 Jobs-to-be-Done (JTBD)

| Job | Frequência | Intensidade da Dor |
|-----|------------|-------------------|
| "Quero saber se estou comendo bem hoje sem precisar calcular nada" | Diária | Alta |
| "Preciso registrar o que comi antes de esquecer" | 4–6x/dia | Alta |
| "Quero entender meu padrão alimentar da semana" | Semanal | Média |
| "Preciso mostrar minha dieta ao nutricionista" | Mensal | Média |
| "Quero ser lembrado de não pular refeições" | Diária | Média |

### 2.2 Análise Competitiva

| Critério | NutriBot | MyFitnessPal | YAZIO | Tecnofit | Samsung Health |
|----------|----------|-------------|-------|---------|---------------|
| Canal | WhatsApp / Telegram | App nativo | App nativo | App nativo | App nativo |
| Fricção de início | Nenhuma | Alta (cadastro longo) | Alta | Alta | Média |
| Idioma PT-BR nativo | ✅ Sim | Parcial | Parcial | ✅ Sim | ✅ Sim |
| Base TACO (brasileira) | ✅ Sim | ❌ Não | ❌ Não | Parcial | ❌ Não |
| Registro por foto | ✅ GPT-4 Vision | ✅ Limitado | ✅ Limitado | ❌ | ✅ |
| Registro por áudio | ✅ Whisper | ❌ | ❌ | ❌ | ❌ |
| Linguagem natural BR | ✅ "arroz com feijão e bife acebolado" | ❌ | ❌ | ❌ | ❌ |
| Alertas ativos | ✅ WhatsApp | Push only | Push only | Push only | Push only |
| Plataforma B2B nutricionista | ✅ (v2) | ❌ | ❌ | ✅ | ❌ |
| Preço entrada | Freemium | Freemium | Freemium | Pago | Gratuito |

**Vantagem competitiva defensável:** Canal WhatsApp + base TACO + NLP em PT-BR coloquial. Nenhum concorrente direto combina os três.

**⚑ Sugestão PM:** Priorizar o lançamento no Telegram antes do WhatsApp. O Telegram tem aprovação de bot instantânea, sem restrições de mensagem ativa, sem custo por mensagem e é muito usado pela comunidade fitness/saúde. WhatsApp entra no Sprint 2 ou 3, após validar o produto.

---

## 3. Personas

### Persona 1 — Ana, 28 anos (Primária)
- **Contexto:** Professora, quer emagrecer 8kg antes do casamento em 6 meses
- **Comportamento atual:** Começou 3 dietas no ano, abandona em 2 semanas. Usa MyFitnessPal por 3 dias e desiste por ser "chato demais"
- **Dor principal:** "Quando lembro de registrar, já esqueci o que comi"
- **Hábito de WhatsApp:** Usa 4+ horas/dia, está em grupos de receitas
- **Gatilho de conversão:** Amiga mostrou o relatório semanal no grupo

### Persona 2 — Ricardo, 35 anos (Primária)
- **Contexto:** Gerente de vendas, treina 3x/semana, quer ganhar massa
- **Comportamento atual:** Conta proteína "na cabeça", erra muito
- **Dor principal:** "Nunca sei se bati a proteína do dia"
- **Hábito:** Usa Telegram para grupos de treino, acha WhatsApp invasivo para bots

### Persona 3 — Dra. Camila, 42 anos (Secundária — B2B)
- **Contexto:** Nutricionista com 40 pacientes, usa planilha Excel para acompanhar diários
- **Dor principal:** "Meus pacientes não preenchem o diário que peço"
- **Valor percebido:** Receber dados reais do paciente sem depender de relato na consulta
- **Disposição a pagar:** Alta — R$ 80–100/mês se economizar 2h semanais de trabalho

### Persona 4 — Dona Maria, 58 anos (Terciária)
- **Contexto:** Diabética, precisa controlar carboidratos, não tem familiaridade com apps
- **Barreira:** "Não sei usar aplicativo, só sei o WhatsApp"
- **Necessidade específica:** Alertas de não pular refeições (hipoglicemia)

---

## 4. Jornada do Usuário (MVP)

### 4.1 Fluxo de Onboarding (primeiros 5 minutos — crítico para retenção)

```
[Usuário adiciona o bot no WhatsApp/Telegram]
         │
         ▼
Bot: "Oi! Eu sou o NutriBot 🥗
     Vou te ajudar a registrar o que você come
     de forma simples, pelo WhatsApp mesmo.
     
     Antes de começar, qual é o seu objetivo?"
     
     [1] Emagrecer
     [2] Ganhar massa
     [3] Manter peso saudável
     [4] Controlar restrição (diabetes, hipertensão...)
         │
         ▼
Bot: "Qual a sua meta calórica diária?
     (Se não sabe, posso calcular — me diz
     seu peso, altura, idade e sexo)"
         │
         ▼
Bot: "Pronto! Meta: 1.800 kcal/dia ✅
     
     Agora me conta o que você comeu hoje!
     Pode escrever assim: 'almocei arroz,
     feijão, frango grelhado e salada'
     Ou manda uma foto do prato 📸"
```

**⚑ Sugestão PM:** Onboarding em no máximo 3 perguntas. Não pedir nome, e-mail, data de nascimento no início. Fricção zero até o primeiro "uau" (momento em que o usuário recebe o primeiro resumo nutricional).

### 4.2 Fluxo de Registro de Refeição (loop principal)

```
Usuário envia: "almocei arroz, feijão, frango
               grelhado e salada com tomate"
         │
         ▼
Bot (< 5s): "Anotei! Aqui está o seu almoço:
     
     🍚 Arroz branco (4 col. sopa) — 176 kcal
     🫘 Feijão carioca (1 concha) — 97 kcal
     🍗 Frango grelhado (150g) — 165 kcal
     🥗 Salada + tomate — 25 kcal
     
     Total: 463 kcal | Prot: 38g | Carb: 52g | Gord: 8g
     
     Saldo do dia: 1.337 kcal restantes (de 1.800)
     ━━━━━━━━━━━━░░░░░░░░░░ 26%
     
     Está correto? [Sim ✅] [Corrigir ✏️]"
         │
         ▼
[Usuário confirma] → Salvo ✅
[Usuário corrige] → "O que precisa ajustar?"
```

### 4.3 Fluxo de Alerta

```
[12:30 - janela do almoço passou sem registro]
         │
         ▼
Bot: "Ei, está na hora do almoço! 🍽️
     Já fez? Me conta o que comeu.
     
     [Adiar 30min ⏰] [Pulei essa refeição]"
```

### 4.4 Fluxo do Relatório Semanal (domingo 20h)

```
Bot envia PDF + resumo no chat:
     "📊 Seu relatório da semana chegou!
     
     ✅ 5 de 7 dias dentro da meta calórica
     🔥 Sequência atual: 5 dias registrando
     📈 +2 dias a mais que na semana passada!
     
     [Ver relatório completo 📄]
     
     💡 Insight da semana: Você consumiu em
     média 38g menos de proteína que o ideal.
     Experimente adicionar um ovo no café ☕"
```

---

## 5. Requisitos Funcionais

### 5.1 Priorização MoSCoW — MVP

#### MUST HAVE (não lança sem isso)

| ID | Requisito |
|----|-----------|
| F01 | Registro de refeição por texto em PT-BR coloquial |
| F02 | Reconhecimento de alimentos via GPT-4o com fallback para confirmação manual |
| F03 | Lookup nutricional (kcal, prot, carb, gordura) — base TACO + USDA local |
| F04 | Exibição de saldo calórico diário após cada registro |
| F05 | Configuração de meta calórica (manual ou calculada por TDEE básico) |
| F06 | Persistência de histórico de registros por usuário |
| F07 | Onboarding conversacional em ≤ 3 perguntas |
| F08 | Bot Telegram funcional (webhook + respostas) |
| F09 | Alertas de refeição via Telegram (horários configuráveis) |
| F10 | Relatório semanal PDF enviado aos domingos |
| F11 | Autenticação por ID de chat (sem login explícito no MVP) |

#### SHOULD HAVE (lança com isso se possível)

| ID | Requisito |
|----|-----------|
| F12 | Registro de refeição por foto (GPT-4 Vision) |
| F13 | Bot WhatsApp Business API |
| F14 | Exibição de macronutrientes (proteína, carboidrato, gordura) no resumo |
| F15 | Streak de dias registrados consecutivos |
| F16 | Comando `/historico` — resumo dos últimos 7 dias |
| F17 | Confirmação antes de salvar registro (sim/corrigir) |

#### COULD HAVE (backlog pós-MVP)

| ID | Requisito |
|----|-----------|
| F18 | Registro por áudio (Whisper transcrição) |
| F19 | Cálculo automático de TDEE (peso, altura, idade, sexo, nível de atividade) |
| F20 | Split de macros personalizável (% prot/carb/gord) |
| F21 | Histórico últimas 4 semanas |
| F22 | Sugestões de substituição alimentar no relatório |

#### WON'T HAVE no MVP (Fase 2+)

| ID | Requisito |
|----|-----------|
| F23 | App nativo iOS/Android |
| F24 | Dashboard web interativo |
| F25 | Painel de nutricionista (B2B) |
| F26 | Integração com wearables (Apple Health, Google Fit) |
| F27 | OCR de cardápio de restaurante |
| F28 | Modelo IA próprio (fine-tuned) |

**⚑ Sugestão PM:** A autenticação no MVP pode ser apenas pelo `chat_id` do Telegram/WhatsApp. Não exigir e-mail/senha no MVP reduz abandono no onboarding em estimados 40–60%.

### 5.2 Requisitos Não-Funcionais

| Requisito | Meta MVP | Meta Prod |
|-----------|----------|-----------|
| Tempo de resposta (texto) | < 5s (p95) | < 1s (p95) |
| Tempo de resposta (foto) | < 10s (p95) | < 3s (p95) |
| Uptime | 99,5% | 99,95% |
| Usuários simultâneos | 1.000 | 100.000+ |
| Precisão texto (top-500 TACO) | > 80% | > 95% |
| Precisão foto | > 75% | > 90% |
| Latência de alerta | < 2min em 99% | < 30s em 99% |
| Cobertura de testes | > 80% (core services) | > 90% |

---

## 6. Requisitos de Dados e LGPD

### 6.1 Entidades Principais (Modelo Conceitual)

```
User
├── channel_id (Telegram chat_id ou WhatsApp phone)
├── channel_type (telegram | whatsapp)
├── daily_calorie_goal
├── goal_type (lose_weight | gain_muscle | maintain | restriction)
├── meal_windows[] (horário + nome de cada refeição)
└── created_at

MealLog
├── user_id
├── logged_at
├── meal_type (breakfast | lunch | dinner | snack)
├── raw_input (texto original do usuário)
├── items[] → FoodItem[]
├── total_calories
├── total_protein_g
├── total_carb_g
└── total_fat_g

FoodItem
├── name
├── quantity_g
├── calories_kcal
├── source (taco | usda | gpt_estimated)
└── confidence_score

WeeklyReport
├── user_id
├── week_start_date
├── pdf_url
└── generated_at
```

### 6.2 Obrigações LGPD (Dados Sensíveis — Art. 11)

| Obrigação | Implementação |
|-----------|--------------|
| Consentimento explícito | Aceite durante onboarding ("Ao continuar, você concorda com nossa Política de Privacidade") |
| Finalidade específica | Dados usados exclusivamente para cálculo nutricional do próprio usuário |
| Direito ao esquecimento | Comando `/deletar_dados` — apaga todos os registros em 72h |
| Portabilidade | Comando `/exportar_dados` — entrega JSON/CSV no chat |
| Minimização de dados | Não coletar mais que o necessário (no MVP: sem nome, sem e-mail) |
| Segurança | TLS 1.3 em trânsito, AES-256 em repouso para campos sensíveis |

**⚑ Sugestão PM:** Implementar os comandos `/deletar_dados` e `/exportar_dados` no Sprint 1. São requisitos legais, não features opcionais.

---

## 7. Arquitetura MVP

### 7.1 Stack

| Camada | Tecnologia | Justificativa |
|--------|-----------|---------------|
| Backend | Python 3.13 + FastAPI | Ecossistema ML/AI maduro; async nativo; tipagem com Pydantic |
| IA | OpenAI GPT-4o | Único modelo para texto + visão + áudio; custo controlado por prompt caching |
| Transcrição áudio | Whisper API (OpenAI) | Suporte PT-BR; integrado no mesmo SDK |
| Banco de dados | PostgreSQL (Supabase) | Supabase oferece free tier generoso + SDK + auth ready |
| ORM + Migrations | SQLAlchemy + Alembic | Padrão Python; migrations versionadas |
| Scheduler | APScheduler | Alertas e relatórios sem Redis/Celery no MVP |
| PDF | WeasyPrint | Python nativo; sem dependência Node.js |
| Bot Telegram | python-telegram-bot v21 | Async; webhook support; amplamente mantido |
| Bot WhatsApp | Z-API ou Twilio | Z-API tem menor latência no Brasil e plano starter acessível |
| Hosting | Railway | Deploy via GitHub; PostgreSQL nativo; custo ~US$ 5–20/mês no MVP |
| Dados nutricionais | TACO + USDA (JSON local) | Sem latência de API externa; custo zero |

**⚑ Sugestão PM:** Usar Supabase em vez de Railway para o banco — oferece free tier com 500MB, dashboard visual, e Row Level Security nativo (já ajuda com LGPD). Para o servidor FastAPI, Railway ou Render.

### 7.2 Fluxo de Processamento

```
[WhatsApp / Telegram]
        │ webhook POST
        ▼
[FastAPI — /webhook/telegram ou /webhook/whatsapp]
        │
        ├─ Tipo: texto → GPT-4o (text) → NutritionService → DB → resposta
        ├─ Tipo: foto  → GPT-4 Vision → NutritionService → DB → resposta
        └─ Tipo: áudio → Whisper → GPT-4o (text) → NutritionService → DB → resposta

[APScheduler — jobs]
        ├─ A cada hora: verifica janelas de refeição abertas → envia alerta se não registrou
        └─ Todo domingo 20h: gera PDF → WeasyPrint → envia no chat

[NutritionService]
        ├─ Lookup em taco.json / usda.json (fuzzy match)
        └─ Fallback: GPT-4o estima kcal/macros se alimento não encontrado (registra como "estimado")
```

### 7.3 Estimativa de Custo Operacional MVP

| Item | Custo Estimado/mês |
|------|--------------------|
| OpenAI API (500 usuários, ~5 msgs/dia) | US$ 80–150 |
| Railway / Render (backend) | US$ 5–20 |
| Supabase (banco) | US$ 0–25 |
| Z-API (WhatsApp) | R$ 97–197 |
| Telegram | Gratuito |
| **Total estimado** | **~US$ 120–250/mês** |

---

## 8. Modelo de Negócio

### 8.1 Planos e Preços

| Plano | Preço | Inclui | Limitação |
|-------|-------|--------|-----------|
| **Free** | Gratuito | Registro por texto, saldo do dia, histórico 3 dias | Máx. 3 registros/dia; sem foto; sem relatório |
| **Premium** | R$ 19,90/mês ou R$ 149,90/ano | Tudo do Free + foto + áudio + alertas + relatório semanal + histórico ilimitado | — |
| **Nutricionista** | R$ 79,90/mês | Premium + painel de até 30 pacientes + notas clínicas | Fase 2 |
| **Clínica/Enterprise** | Sob consulta | White-label + SLA + onboarding dedicado | Fase 3 |

**⚑ Sugestão PM — ajuste no Free tier:** O Free da v1.0 era generoso demais (histórico 7 dias, sem limite de registros). A sugestão acima limita em **3 registros/dia e 3 dias de histórico**, criando fricção suficiente para upgrade sem bloquear o "momento uau". O relatório semanal deve ser Premium — é o feature de maior valor percebido e o melhor gatilho de upgrade.

### 8.2 Funil de Conversão Esperado

```
Instalação do bot (100%)
        │
        ▼ ~70%
Completa onboarding (3 perguntas)
        │
        ▼ ~50%
Registra primeira refeição no D1
        │
        ▼ ~35%
Ativo D7 (retém após primeira semana)
        │
        ▼ ~15%
Recebe 1º relatório semanal e engaja
        │
        ▼ ~5–8%
Converte para Premium
```

**⚑ Sugestão PM:** O domingo após o primeiro relatório é o maior momento de conversão. Incluir no relatório gratuito um "preview bloqueado" das sugestões personalizadas ("Você teria recebido 3 sugestões específicas para sua meta. Acesse o Premium para ver →").

### 8.3 Unit Economics (Projeção 12 meses)

| Métrica | Estimativa |
|---------|-----------|
| CAC (orgânico/WOM) | R$ 5–15 |
| CAC (pago) | R$ 25–60 |
| LTV Premium anual | R$ 149,90 |
| LTV Premium mensal (12m churn 5%/mês) | ~R$ 100 |
| Payback period (orgânico) | < 1 mês |
| Margem bruta (excluindo OpenAI) | ~70% |

---

## 9. Cronograma MVP — Detalhado

### Sprint 1 (Semanas 1–2) — Canal + Registro Texto
**Entregáveis:**
- [ ] Setup infra: Railway + Supabase + repositório + CI/CD básico
- [ ] Bot Telegram funcional (webhook, health check)
- [ ] Onboarding conversacional (3 perguntas → salva meta no DB)
- [ ] Registro por texto → GPT-4o → lookup TACO/USDA → resposta com kcal/macros
- [ ] Saldo calórico diário no retorno
- [ ] Comandos `/deletar_dados` e `/exportar_dados` (LGPD)
- [ ] Testes unitários: NutritionService (> 80% cobertura)

**Critério de aceite do Sprint 1:** Bot responde em < 5s para 10 alimentos diferentes testados manualmente, com precisão > 80%.

### Sprint 2 (Semanas 3–4) — Foto + Confirmação + WhatsApp
**Entregáveis:**
- [ ] Reconhecimento de foto via GPT-4 Vision
- [ ] Fluxo de confirmação (sim/corrigir) antes de salvar
- [ ] Transcrição de áudio via Whisper (PT-BR)
- [ ] Bot WhatsApp Business (Z-API webhook)
- [ ] Streak de dias registrados

### Sprint 3 (Semanas 5–6) — Alertas + Meta
**Entregáveis:**
- [ ] APScheduler configurado para verificação de janelas de refeição
- [ ] Envio de alertas no Telegram e WhatsApp
- [ ] Configuração de horários de refeição pelo usuário (`/configurar`)
- [ ] Opção de snooze e silenciar alertas
- [ ] Cálculo de TDEE básico (opcional no onboarding)

### Sprint 4 (Semanas 7–8) — Relatório Semanal
**Entregáveis:**
- [ ] Geração de PDF com WeasyPrint (template fixo)
- [ ] Job domingo 20h → gera e envia relatório
- [ ] Conteúdo: resumo semanal, gráfico de barras de kcal, top alimentos, comparativo
- [ ] Sugestões básicas por IA (baseadas em déficit/excesso)
- [ ] Histórico últimas 4 semanas (`/relatorios`)

### Sprint 5–6 (Semanas 9–12) — Polimento + Beta
**Entregáveis:**
- [ ] UX review de todas as mensagens do bot (tom, clareza)
- [ ] Onboarding A/B test (versão A: 3 perguntas / versão B: "só manda o que comeu agora")
- [ ] Tratamento de erros amigável (alimento não reconhecido → pede mais detalhes)
- [ ] 50 usuários beta fechado → NPS survey
- [ ] Documentação OpenAPI atualizada
- [ ] Monitoramento: Sentry (erros) + logs estruturados

---

## 10. Métricas de Sucesso (AARRR)

| Fase | Métrica | Meta MVP (12 semanas) |
|------|---------|----------------------|
| **Acquisition** | Novos usuários/semana | 50+ (orgânico) |
| **Activation** | % que registra refeição no D1 | > 50% |
| **Retention** | DAU/MAU ratio | > 30% |
| **Retention** | D7 retention | > 35% |
| **Retention** | D30 retention | > 20% |
| **Revenue** | Conversão Free → Premium | > 5% |
| **Revenue** | MRR ao fim do Sprint 6 | R$ 500+ (beta) |
| **Referral** | % usuários que indicaram 1+ amigo | > 15% |
| **Quality** | Precisão reconhecimento texto | > 80% |
| **Quality** | Precisão reconhecimento foto | > 75% |
| **Quality** | NPS pós-relatório semanal | > 40 |
| **Quality** | Custo/usuário ativo | < R$ 5/mês |

---

## 11. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Custo OpenAI cresce com escala | Alta | Alto | Implementar cache de respostas (alimentos comuns); migrar para modelos menores para lookup simples |
| WhatsApp recusa ou bloqueia conta business | Média | Alto | Lançar Telegram primeiro; manter WhatsApp como canal 2; documentar caso de uso claramente |
| Imprecisão em pratos regionais BR | Alta | Médio | Base TACO é forte; feedback loop ativo; usuário pode corrigir e isso treina o sistema |
| Abandono pós-onboarding (D1 < 50%) | Média | Alto | Teste A/B de onboarding; "zero-friction first" (primeiro registro antes de qualquer configuração) |
| LGPD — autuação por dados sensíveis | Baixa | Muito Alto | Jurídico especializado no Sprint 1; DPO designado antes do lançamento beta |
| Concorrente grande replica em < 6 meses | Baixa | Médio | Vantagem de base de usuários e dados; acelerar B2B (nutricionistas) como moat |
| Rate limits da OpenAI em pico | Média | Médio | Fila de processamento + retry logic + múltiplas chaves de API |

---

## 12. Definição de Pronto (Definition of Done)

### Por Feature
- Código revisado por pelo menos 1 pessoa
- Testes unitários escritos (cobertura > 80% do service afetado)
- Mensagens do bot revisadas para tom e clareza
- Documentada no OpenAPI spec (para endpoints REST)
- Testada manualmente no ambiente de staging com casos de borda

### Por Sprint
- Demo funcionando ao final do sprint
- Nenhum bug crítico aberto
- README e CLAUDE.md atualizados se arquitetura mudou
- Métricas de qualidade (precisão, latência) medidas e registradas

---

## 13. Glossário

| Termo | Definição |
|-------|-----------|
| TACO | Tabela Brasileira de Composição de Alimentos (UNICAMP) — base nutricional brasileira |
| USDA | United States Department of Agriculture — base global de composição alimentar |
| TDEE | Total Daily Energy Expenditure — gasto calórico diário total estimado |
| Macro | Macronutriente: proteína, carboidrato ou gordura |
| NLP | Natural Language Processing — processamento de linguagem natural |
| JTBD | Jobs to be Done — framework de análise de motivação do usuário |
| PLG | Product-Led Growth — crescimento impulsionado pelo uso do produto |
| CAC | Customer Acquisition Cost — custo de aquisição de cliente |
| LTV | Lifetime Value — valor total gerado por um cliente ao longo do tempo |
| AARRR | Acquisition, Activation, Retention, Revenue, Referral — framework de métricas de startup |
| LGPD | Lei Geral de Proteção de Dados (Brasil, Lei 13.709/2018) |
| DPO | Data Protection Officer — encarregado de proteção de dados |
| MoSCoW | Must / Should / Could / Won't — framework de priorização de requisitos |
| Free tier | Camada gratuita do produto com funcionalidades limitadas |
| Churn | Taxa de cancelamento ou abandono de usuários |
| NPS | Net Promoter Score — métrica de satisfação e intenção de indicação |
| WOM | Word of Mouth — indicação boca a boca |
| Webhook | Endpoint HTTP que recebe eventos em tempo real (mensagens do Telegram/WhatsApp) |
| Streak | Sequência consecutiva de dias com registro completo |
| Fuzzy match | Busca aproximada de texto — encontra "arros" mesmo com erro de digitação |

---

## 14. Próximos Passos

1. **Aprovação deste PRD** pelos stakeholders (prazo: 5 dias úteis)
2. **Validação de canal:** testar onboarding no Telegram com 5–10 usuários reais antes de construir
3. **Setup de infra base:** repositório GitHub + Railway + Supabase + variáveis de ambiente
4. **Contratação da API:** OpenAI key (Tier 2) + Z-API ou Twilio WhatsApp
5. **Sprint 1 inicia** em até 1 semana após aprovação

---

*NutriBot PRD v2.0 — Documento Interno — Revisão PM/Negócios sobre v1.0*
