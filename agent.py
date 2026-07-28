"""Agente diario de reporting de Pipedrive para TVE.

Solo lee datos de Pipedrive (nunca crea/edita/borra nada) y manda un reporte
a Telegram. Todos los días manda el reporte diario. Los lunes suma el
reporte semanal. El día 1 de cada mes suma el reporte mensual.
"""
import asyncio
import logging
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipedrive-agent")

PD_TOKEN = os.environ["PIPEDRIVE_API_TOKEN"]
PD_DOMAIN = os.environ["PIPEDRIVE_DOMAIN"]
PD_BASE = f"https://{PD_DOMAIN}.pipedrive.com/api/v1/"

MONTHLY_TARGET_WON = 13

STAGE_NAMES = {
    1: "Lead in", 6: "Primer contacto", 4: "Presupuesto enviado",
    2: "Segundo contacto", 3: "Visita programada", 5: "Negociando",
}
STAGE_ORDER = ["Lead in", "Primer contacto", "Presupuesto enviado",
               "Segundo contacto", "Visita programada", "Negociando"]

LEAD_SOURCE_FIELD = "4684c6f661de812ab6f0a3fc1d402c97dfc3d7d8"
LEAD_SOURCE_OPTIONS = {
    16: "La Nacion", 17: "Clarin", 18: "ACA", 19: "Boca a boca", 20: "Facebook",
    27: "Mailing", 21: "Google", 22: "Revista Viva", 23: "Revista ascensor",
    24: "Revista Subir y bajar", 35: "Instagram", 36: "Mercadolibre",
    70: "El Ombu Mall", 26: "Otro",
}

TELEGRAM_MAX_CHARS = 4096


# ── Pipedrive helpers ──────────────────────────────────────────────────────
def pd_get(endpoint, params=None):
    p = {"api_token": PD_TOKEN}
    if params:
        p.update(params)
    r = requests.get(PD_BASE + endpoint, params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_since(time_field, cutoff_dt, extra_params=None):
    """Trae deals ordenados por time_field DESC hasta cruzar cutoff_dt."""
    results = []
    start = 0
    while True:
        params = {"start": start, "limit": 500, "sort": f"{time_field} DESC"}
        if extra_params:
            params.update(extra_params)
        data = pd_get("deals", params)
        rows = data.get("data") or []
        stop = False
        for deal in rows:
            t = deal.get(time_field)
            if not t:
                continue
            dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            if dt < cutoff_dt:
                stop = True
                break
            results.append(deal)
        if stop:
            break
        pag = data.get("additional_data", {}).get("pagination", {})
        if not pag.get("more_items_in_collection"):
            break
        start = pag.get("next_start")
    return results


def get_owner_name(deal):
    owner = deal.get("user_id")
    if isinstance(owner, dict):
        return owner.get("name", "Sin owner")
    return "Sin owner"


def get_lead_source(deal):
    val = deal.get(LEAD_SOURCE_FIELD)
    try:
        val_int = int(val) if val is not None else None
    except (ValueError, TypeError):
        val_int = None
    return LEAD_SOURCE_OPTIONS.get(val_int, "Sin dato" if val is None else f"?{val}")


def get_product_names(deal):
    if not deal.get("products_count"):
        return "-"
    data = pd_get(f"deals/{deal['id']}/products")
    rows = data.get("data") or []
    if not rows:
        return "-"
    return ", ".join(p.get("name", "?") for p in rows)


def fmt_money(deal):
    val = deal.get("value") or 0
    cur = deal.get("currency", "")
    return f"{cur} {val:,.0f}" if val else "sin valor cargado"


# ── Reporte diario ──────────────────────────────────────────────────────────
def build_daily_report(today):
    start_today = datetime(today.year, today.month, today.day)

    created = [d for d in fetch_since("add_time", start_today)
               if datetime.strptime(d["add_time"], "%Y-%m-%d %H:%M:%S") >= start_today]
    won = [d for d in fetch_since("won_time", start_today)
           if d.get("won_time") and datetime.strptime(d["won_time"], "%Y-%m-%d %H:%M:%S") >= start_today]
    lost = [d for d in fetch_since("lost_time", start_today)
            if d.get("lost_time") and datetime.strptime(d["lost_time"], "%Y-%m-%d %H:%M:%S") >= start_today]

    lines = [f"📊 *Reporte diario Pipedrive — {today.strftime('%d/%m/%Y')}*", ""]

    lines.append(f"🆕 *Deals nuevos ({len(created)})*")
    if created:
        for d in created:
            product = get_product_names(d)
            lines.append(
                f"• {d.get('title','(sin título)')} — {fmt_money(d)}\n"
                f"   Vendedor: {get_owner_name(d)} | Fuente: {get_lead_source(d)} | Producto: {product}"
            )
    else:
        lines.append("_Sin deals nuevos hoy_")
    lines.append("")

    lines.append(f"✅ *Ganados hoy ({len(won)})*")
    if won:
        for d in won:
            lines.append(f"• {d.get('title','(sin título)')} — {fmt_money(d)} | {get_owner_name(d)}")
    else:
        lines.append("_Sin ganados hoy_")
    lines.append("")

    lines.append(f"❌ *Perdidos hoy ({len(lost)})*")
    if lost:
        for d in lost:
            lines.append(f"• {d.get('title','(sin título)')} | {get_owner_name(d)}")
    else:
        lines.append("_Sin perdidos hoy_")

    return "\n".join(lines)


# ── Reporte semanal (lunes, sobre la semana que terminó ayer) ───────────────
def build_weekly_report(today):
    week_end = datetime(today.year, today.month, today.day)  # hoy 00:00 = fin de la semana pasada
    week_start = week_end - timedelta(days=7)
    prev_week_start = week_start - timedelta(days=7)

    def counts_in_range(time_field, start, end):
        rows = fetch_since(time_field, start)
        return [d for d in rows if d.get(time_field)
                and start <= datetime.strptime(d[time_field], "%Y-%m-%d %H:%M:%S") < end]

    created_this = counts_in_range("add_time", week_start, week_end)
    won_this = counts_in_range("won_time", week_start, week_end)
    lost_this = counts_in_range("lost_time", week_start, week_end)

    created_prev = counts_in_range("add_time", prev_week_start, week_start)
    won_prev = counts_in_range("won_time", prev_week_start, week_start)
    lost_prev = counts_in_range("lost_time", prev_week_start, week_start)

    def delta(curr, prev):
        d = curr - prev
        return f"({'+' if d>=0 else ''}{d} vs sem. anterior)"

    lines = [
        "",
        f"📅 *Reporte semanal — {week_start.strftime('%d/%m')} al {(week_end-timedelta(days=1)).strftime('%d/%m')}*",
        "",
        f"Nuevos: {len(created_this)} {delta(len(created_this), len(created_prev))}",
        f"Ganados: {len(won_this)} {delta(len(won_this), len(won_prev))}",
        f"Perdidos: {len(lost_this)} {delta(len(lost_this), len(lost_prev))}",
        "",
        "*Por vendedor esta semana:*",
    ]

    by_owner = defaultdict(lambda: {"won": 0, "lost": 0})
    for d in won_this:
        by_owner[get_owner_name(d)]["won"] += 1
    for d in lost_this:
        by_owner[get_owner_name(d)]["lost"] += 1

    if by_owner:
        for owner in sorted(by_owner, key=lambda o: -(by_owner[o]["won"] + by_owner[o]["lost"])):
            v = by_owner[owner]
            lines.append(f"• {owner}: {v['won']} ganados | {v['lost']} perdidos")
    else:
        lines.append("_Sin actividad de cierre esta semana_")

    return "\n".join(lines)


# ── Reporte mensual (día 1, sobre el mes que terminó) ───────────────────────
def build_monthly_report(today):
    first_of_this_month = date(today.year, today.month, 1)
    last_month_end = first_of_this_month
    if first_of_this_month.month == 1:
        last_month_start = date(first_of_this_month.year - 1, 12, 1)
    else:
        last_month_start = date(first_of_this_month.year, first_of_this_month.month - 1, 1)

    if last_month_start.month == 1:
        prev2_start = date(last_month_start.year - 1, 12, 1)
    else:
        prev2_start = date(last_month_start.year, last_month_start.month - 1, 1)

    last_month_start_dt = datetime.combine(last_month_start, datetime.min.time())
    last_month_end_dt = datetime.combine(last_month_end, datetime.min.time())
    prev2_start_dt = datetime.combine(prev2_start, datetime.min.time())

    def in_range(time_field, start, end):
        rows = fetch_since(time_field, start)
        return [d for d in rows if d.get(time_field)
                and start <= datetime.strptime(d[time_field], "%Y-%m-%d %H:%M:%S") < end]

    created = in_range("add_time", last_month_start_dt, last_month_end_dt)
    won = in_range("won_time", last_month_start_dt, last_month_end_dt)
    lost = in_range("lost_time", last_month_start_dt, last_month_end_dt)
    won_prev = in_range("won_time", prev2_start_dt, last_month_start_dt)

    lines = [
        "",
        f"🗓️ *Overview mensual — {last_month_start.strftime('%B %Y')}*",
        "",
        f"Deals creados: {len(created)}",
        f"Ganados: {len(won)} (mes anterior: {len(won_prev)})",
        f"Perdidos: {len(lost)}",
        "",
        f"🎯 *Target: {len(won)}/{MONTHLY_TARGET_WON} equipos vendidos* "
        f"({len(won)/MONTHLY_TARGET_WON*100:.0f}%)",
        "",
        "*Fuente de los deals creados:*",
    ]

    src_counter = Counter(get_lead_source(d) for d in created)
    if src_counter:
        for label, count in src_counter.most_common():
            lines.append(f"• {label}: {count}")
    else:
        lines.append("_Sin deals creados el mes pasado_")

    return "\n".join(lines)


# ── Telegram ─────────────────────────────────────────────────────────────
def split_message(text, limit=TELEGRAM_MAX_CHARS):
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


async def _send_async(token, chat_id, chunks):
    from telegram import Bot
    bot = Bot(token=token)
    async with bot:
        for chunk in chunks:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            await asyncio.sleep(0.5)


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN_CRM"]
    chat_id = os.environ["TELEGRAM_CHAT_ID_CRM"]
    chunks = split_message(text)
    asyncio.run(_send_async(token, chat_id, chunks))


def _send_error(fn, err):
    msg = f"🔴 *Error en agente Pipedrive*\n\nFunción: `{fn}`\nError: {err}"
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN_CRM", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID_CRM", "")
        if token and chat_id:
            asyncio.run(_send_async(token, chat_id, [msg]))
    except Exception as e:
        log.error(f"No se pudo enviar error a Telegram: {e}")


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    today = date.today()
    log.info(f"=== Pipedrive agent — {today} ===")

    try:
        daily = build_daily_report(today)
    except Exception as e:
        _send_error("build_daily_report", str(e))
        raise

    message = daily

    if today.weekday() == 0:  # lunes
        try:
            message += "\n" + build_weekly_report(today)
        except Exception as e:
            log.warning(f"build_weekly_report falló: {e}")

    if today.day == 1:
        try:
            message += "\n" + build_monthly_report(today)
        except Exception as e:
            log.warning(f"build_monthly_report falló: {e}")

    try:
        send_telegram(message)
        log.info("Reporte enviado OK")
    except Exception as e:
        _send_error("send_telegram", str(e))
        raise


if __name__ == "__main__":
    main()
