# TVE Pipedrive — Agente diario de reporting

Agente automático de solo lectura que corre todos los días a las 9am Argentina
y manda un reporte a Telegram con lo que pasó en el CRM.

**No ejecuta ningún cambio en Pipedrive.** Solo lee y reporta.

- **Todos los días:** deals nuevos (con fuente, vendedor, producto, valor), ganados y perdidos del día.
- **Los lunes, además:** comparativo semanal (esta semana vs. la anterior, por vendedor).
- **El día 1 de cada mes, además:** overview del mes anterior (por fuente, ganados/perdidos vs. mes previo, progreso vs. target de 13 equipos vendidos).

---

## PASO 1 — Crear el bot de Telegram (separado del de Google Ads)

1. Abrí Telegram y buscá `@BotFather`
2. Mandá `/newbot`
3. Elegí un nombre (ej: `TVE Pipedrive Report`)
4. Elegí un username que termine en `bot` (ej: `tve_pipedrive_report_bot`)
5. Guardá el **token** que te da — es tu `TELEGRAM_BOT_TOKEN_CRM`

## PASO 2 — Obtener el TELEGRAM_CHAT_ID_CRM

1. Mandale cualquier mensaje a ese bot nuevo (ej: "hola")
2. Abrí en el navegador: `https://api.telegram.org/bot[TOKEN]/getUpdates`
3. Buscá `"chat": {"id": ...}` — ese número es tu `TELEGRAM_CHAT_ID_CRM`

## PASO 3 — Crear el repositorio en GitHub

```bash
cd "/Users/mateo/Documents/Claude Code/TVE/g-ads/pipedrive-agent"
git init
git add .
git commit -m "Initial commit — TVE Pipedrive daily agent"
git remote add origin https://github.com/TU_USUARIO/tve-pipedrive-agent.git
git push -u origin main
```

## PASO 4 — Configurar GitHub Secrets

En el repo → **Settings → Secrets and variables → Actions** → agregar:

| Secret | Valor |
|--------|-------|
| `PIPEDRIVE_API_TOKEN` | Tu token de API de Pipedrive |
| `PIPEDRIVE_DOMAIN` | `transportesverticales` |
| `TELEGRAM_BOT_TOKEN_CRM` | El token del bot nuevo (paso 1) |
| `TELEGRAM_CHAT_ID_CRM` | Tu chat ID (paso 2) |

## PASO 5 — Test manual

**Actions → TVE Pipedrive Daily Report → Run workflow.** Esperá ~30 segundos y revisá Telegram.

---

## Desarrollo local

```bash
cd "/Users/mateo/Documents/Claude Code/TVE/g-ads/pipedrive-agent"
pip install -r requirements.txt
# Con las 4 variables de entorno seteadas:
python agent.py
```
