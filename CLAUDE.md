# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NutriBot is a multicanal nutritional tracking chatbot (WhatsApp, Telegram, eventually native app + web) that lets users log meals via text, audio, or photo in natural language. It identifies foods, calculates calories and macronutrients using the TACO (Brazilian) and USDA databases, tracks meal schedules, sends proactive alerts, and delivers weekly PDF reports with AI-generated personalized suggestions.

The PRD (`NutriBot_PRD_v1.0.docx`) is the authoritative source for scope, priorities, and acceptance criteria.

## Current State

The repository is **pre-code** — only the PRD and `.venv` (Python 3.13, pip only) exist. MVP development is planned for 8–12 weeks across 5 sprints.

## MVP Architecture

**Backend:** Python FastAPI (monolith for MVP)  
**AI:** OpenAI GPT-4o — handles text NLP, GPT-4 Vision for photo recognition, Whisper for audio transcription (single API)  
**Database:** PostgreSQL (Railway or Supabase)  
**Alerts:** Cron jobs (`APScheduler` or similar) — no distributed queue in MVP  
**PDF reports:** Puppeteer (HTML template → PDF) or WeasyPrint  
**Auth:** JWT + bcrypt  
**Channels:** WhatsApp Business API (via Twilio or Z-API) + Telegram Bot (python-telegram-bot)  
**Nutrition data:** TACO + USDA FoodData Central as local JSON — no external API call  
**Hosting:** Railway or Render  

## Sprint Sequence (MVP Roadmap)

| Sprint | Focus |
|--------|-------|
| 1 | Infra setup, WhatsApp/Telegram bots, text-based meal registration, nutrition lookup |
| 2 | Photo recognition (GPT-4 Vision), audio transcription, user confirmation flow |
| 3 | Meal window alerts/reminders, daily calorie goal configuration |
| 4 | Weekly PDF report generation, AI suggestions, report history |
| 5–6 | UX polish, onboarding, closed beta launch |

## Development Commands

Once the project is scaffolded, commands will follow this pattern:

```bash
# Activate venv (PowerShell)
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run FastAPI dev server
uvicorn app.main:app --reload

# Run tests
pytest

# Run a single test file
pytest tests/test_nutrition.py -v
```

Environment variables required (`.env` file):
- `OPENAI_API_KEY` — GPT-4o + Vision + Whisper
- `DATABASE_URL` — PostgreSQL connection string
- `TELEGRAM_BOT_TOKEN`
- `WHATSAPP_API_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID`
- `JWT_SECRET`

## Key Domain Constraints

- **Nutrition database priority:** TACO (Brazilian) > USDA. Always prefer TACO entries for Brazilian foods.
- **Language:** Portuguese (Brazilian), including gírias and regionalismos alimentares.
- **LGPD compliance:** Health data is classified as *dados sensíveis* (Art. 11). Explicit consent required on onboarding; support right-to-deletion within 72h.
- **MVP acceptance thresholds:** >80% text recognition accuracy on top-500 TACO foods; >75% photo identification; alerts delivered within 2 min in 99% of cases.

## Project Structure (Planned)

```
app/
  main.py          # FastAPI app factory
  routers/         # Endpoint groupings (meals, users, reports, webhooks)
  services/        # Business logic (ai_processing, nutrition, scheduler, pdf)
  models/          # SQLAlchemy models
  schemas/         # Pydantic request/response schemas
  db/              # Database session, migrations (Alembic)
data/
  taco.json        # TACO nutritional table
  usda.json        # USDA FoodData Central subset
tests/
```
