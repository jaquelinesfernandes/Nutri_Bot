# Sugestões de Melhoria — Painel B2B (Nutricionistas)

> Data: 2026-09-15 · Status: Backlog · Baseado em análise do Sprint Admin-2

---

## 🔬 Visão Geral

O painel B2B atual (`/admin/nutricionistas`) exibe métricas agregadas por nutricionista (trial, pacientes, status). As sugestões abaixo adicionam **granularidade clínica** e **ferramentas de gestão** sem exigir mudanças de modelo de dados.

---

## 📋 Sugestões Priorizadas

### 1. 📊 Progresso dos Pacientes por Nutricionista (Alta prioridade)

**O que é:** No detalhe de cada nutricionista, adicionar uma aba ou seção mostrando o progresso dos pacientes:
- Gráfico de kcal diário vs. meta calórica (últimos 14 dias por paciente)
- Indicador de aderência: % de dias com pelo menos 1 refeição registrada
- Badge de "em dia" / "em risco" / "inativo" por paciente

**Implementação:**
```sql
SELECT u.first_name, u.id,
       AVG(ml.total_calories) as avg_kcal,
       COUNT(DISTINCT DATE(ml.logged_at)) as active_days
FROM nutritionist_patients np
JOIN users u ON u.id = np.patient_id
JOIN meal_logs ml ON ml.user_id = np.patient_id
WHERE np.nutritionist_id = :nutri_id
  AND np.status = 'active'
  AND ml.logged_at > NOW() - INTERVAL '14 days'
GROUP BY u.id, u.first_name
```

**Esforço:** Médio (~1 dia) — query + canvas chart na template `admin_usuario.html`

---

### 2. ⚠️ Alertas de Inatividade por Paciente (Alta prioridade)

**O que é:** Sistema de alertas configuráveis por nutricionista/paciente:
- "Paciente X não registra refeições há 3 dias"
- Badge vermelho na lista de pacientes do nutricionista
- Botão "Notificar paciente" direto pelo painel admin (já existe `NotificationService`)

**Implementação:**
- Query de pacientes sem `meal_logs` nos últimos N dias
- Parâmetro `alert_threshold_days` no perfil do paciente (default: 2)
- Botão POST `/admin/api/nutricionistas/{nutri_id}/notificar-paciente/{patient_id}`

**Esforço:** Baixo (~4h) — query simples + botão similar ao B2C notificar

---

### 3. 📝 Notas Clínicas no Painel Admin (Média prioridade)

**O que é:** Visualizar e adicionar notas clínicas dos pacientes diretamente do painel admin:
- Exibir as notas existentes (tabela `clinical_notes` do Sprint B2B-2)
- Botão "+ Nota de observação" para o admin registrar observações de suporte
- Campo `source: 'admin'` para diferenciar de notas do nutricionista

**Implementação:**
- GET `/admin/api/pacientes/{patient_id}/notas` — lista notas clínicas
- POST `/admin/api/pacientes/{patient_id}/notas` — adiciona nota com `source='admin'`
- Modal na `admin_usuario.html` para pacientes vinculados

**Esforço:** Médio (~1 dia) — depende do modelo `ClinicalNote` do Sprint B2B-2

---

### 4. 🔄 Funil de Conversão Trial → Pago (Média prioridade)

**O que é:** No painel de nutricionistas, uma seção mostrando o funil de conversão das nutricionistas trial:

```
Cadastradas (trial) → Adicionaram pacientes → Pacientes ativos → Converteram para pago
```

- Taxa de conversão mês a mês
- Nutricionistas em trial com alta atividade de pacientes = candidatas a conversão proativa
- Destaque para "hot leads": trial expirando em 7d + pelo menos 3 pacientes ativos

**Implementação:** Queries SQL agregadas + seção na `admin_nutricionistas.html`

**Esforço:** Baixo-médio (~4-6h) — apenas queries + template

---

### 5. 🔗 Botão "Copiar Deep Link de Convite" (Baixa prioridade)

**O que é:** Na lista de nutricionistas (e no detalhe), mostrar o deep link de convite gerado para cada nutricionista e um botão "📋 Copiar".

**Implementação:**
```html
<button onclick="navigator.clipboard.writeText('{{ invite_link }}')">📋 Copiar link</button>
```

**Esforço:** Trivial (~30min) — só precisa passar o `invite_link` ao template

---

### 6. 📈 Dashboard B2B Consolidado (Baixa prioridade)

**O que é:** Uma seção no dashboard principal com métricas B2B chave:
- Crescimento MoM de nutricionistas (linha de tendência)
- Receita média por nutricionista (MRR B2B)
- NPS implícito: nutricionistas com mais de 5 pacientes ativos = "advocates"

**Implementação:** Dados já parcialmente disponíveis no dashboard. Ampliar o card "Nutricionistas B2B" existente.

**Esforço:** Baixo (~3h)

---

## 🗓️ Sugestão de Roadmap

| Prioridade | Item | Sprint |
|-----------|------|--------|
| Alta | Progresso dos pacientes | Admin-3 |
| Alta | Alertas de inatividade | Admin-3 |
| Média | Notas clínicas no admin | Admin-3 |
| Média | Funil trial → pago | Admin-4 |
| Baixa | Copiar deep link | Admin-3 (trivial) |
| Baixa | Dashboard B2B consolidado | Admin-4 |

---

## 🔒 Considerações LGPD

- Notas clínicas adicionadas pelo admin devem ser registradas no `admin_logs` com `action="clinical_note_admin"`
- Notificações enviadas pelo admin para pacientes de nutricionistas devem ter ciência do nutricionista responsável
- Acesso a dados de saúde de pacientes pelo admin deve ser logado individualmente

---

*Documento gerado automaticamente a partir da sessão de análise do Sprint Admin-2.*
