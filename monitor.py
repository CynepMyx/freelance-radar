"""FreelanceRadar — Kwork monitor with Telegram alerts."""
import asyncio
import logging
import os
import sys

import asyncpg
import httpx
import redis.asyncio as aioredis

sys.path.insert(0, os.path.dirname(__file__))
from kwork_api import KworkApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("freelance-radar")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis-container:6379")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "120"))
MIN_PAGES = int(os.environ.get("MIN_PAGES", "3"))
KEYWORDS = [k.strip().lower() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]

PARENT_CATEGORY_IDS = {int(x) for x in os.environ.get("PARENT_CATEGORY_IDS", "11").split(",") if x.strip()}
EXCLUDE_CATEGORY_IDS = {int(x) for x in os.environ.get("EXCLUDE_CATEGORY_IDS", "").split(",") if x.strip()}

KWORK_URL = "https://kwork.ru/projects/{id}"
PG_DSN = os.environ.get("PG_DSN", "postgresql://fr_user:fr_pass_2026@fr-postgres:5432/freelance_radar")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SCORE_THRESHOLD = int(os.environ.get("SCORE_THRESHOLD", "60"))

paused = False
scoring_enabled = True


async def send_telegram(client: httpx.AsyncClient, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    await client.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


SCORE_PROMPT = """\
Ты — AI-фильтр заказов Kwork для фрилансера.

Его профиль:
- Linux / Ubuntu / Debian / CentOS — системное администрирование
- VPS / хостинг / серверы
- nginx / apache / SSL / HTTPS / Let's Encrypt
- Docker / docker-compose
- WordPress: перенос, ускорение, кеш, безопасность, лечение проблем, настройка
- диагностика ошибок, падений, тормозов на сервере и сайте
- бэкапы, миграции, восстановление данных
- аудит сервера / сайта / безопасности
- настройка, починить, ускорить, перенести, восстановить, защитить — это его задачи

Сильный плюс:
- диагностика, аудит, поиск причины проблемы
- исправление аварии, ошибки, падения
- перенос, миграция существующей инфраструктуры
- "починить", "разобраться", "настроить", "ускорить"

НЕ подходит:
- дизайн, верстка, создание сайта с нуля
- frontend / backend разработка как основная задача
- мобильные приложения
- 1С, бухгалтерия
- SEO, SMM, реклама, копирайтинг, маркетинг
- чистая разработка (написать код, сделать функционал)

Шкала:
- 80-100: явно подходит, профильная задача
- 60-79: скорее подходит, есть нюансы
- 40-59: пограничный заказ, неясный или смешанный
- 0-39: не подходит

Правила:
- оценивай по сути задачи, не по платформе (WordPress сам по себе не значит высокий балл — важно ЧТО нужно сделать)
- если основная суть заказа — разработка / верстка / дизайн, даже на WP — это не его профиль, ставь низкий балл
- если заказ мутный, короткий — 40-55
- если задача явно не его профиля — ставь 0-30, не натягивай
- будь строгим и консервативным
- если объём большой, а бюджет явно занижен — снижай score на 10-20

Отвечай ТОЛЬКО валидным JSON без markdown:
{"score": <0-100>, "reason": "<одно короткое предложение>"}
"""


async def score_project(http: httpx.AsyncClient, title: str, description: str) -> tuple[int, str]:
    if not OPENROUTER_API_KEY:
        return 50, "no api key"
    try:
        resp = await http.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "deepseek/deepseek-chat",
                "messages": [
                    {"role": "system", "content": SCORE_PROMPT},
                    {"role": "user", "content": f"Заказ: {title}\n\n{description}"},
                ],
                "max_tokens": 100,
                "temperature": 0,
            },
            timeout=20,
        )
        import json as _json
        content = resp.json()["choices"][0]["message"]["content"].strip()
        content = content.strip("```json").strip("```").strip()
        data = _json.loads(content)
        return int(data["score"]), data.get("reason", "")
    except Exception as e:
        log.warning("Score error: %s", e)
        return 50, "error"


def format_project(p: dict, score: int | None = None, reason: str = "") -> str:
    title = p.get("title", "—")
    price = p.get("price", "?")
    price_max = p.get("possible_price_limit")
    offers = p.get("offers", 0)
    hours_left = p.get("time_left", 0) // 3600
    hired_pct = p.get("user_hired_percent", 0)
    url = KWORK_URL.format(id=p.get("id"))
    budget = f"до {price} ₽"
    if price_max and price_max > price:
        budget += f" (до {price_max} ₽)"
    desc = p.get("description", "") or ""
    import re
    desc = re.sub(r"<[^>]+>", " ", desc).strip()
    desc = re.sub(r"\s+", " ", desc)
    if len(desc) > 3500:
        desc = desc[:3500].rsplit(" ", 1)[0] + "…"
    desc_line = f"\n📝 {desc}" if desc else ""
    score_line = f"\n🎯 Score: {score} — {reason}" if score is not None else ""
    return (
        f"🆕 <b>{title}</b>\n"
        f"💰 {budget}  |  📩 {offers}  |  ⏳ {hours_left}ч  |  🤝 {hired_pct}%"
        f"{desc_line}"
        f"{score_line}\n"
        f"🔗 <a href='{url}'>Открыть на Kwork</a>"
    )


def matches_filter(p: dict) -> bool:
    if EXCLUDE_CATEGORY_IDS and p.get("category_id") in EXCLUDE_CATEGORY_IDS:
        return False
    if KEYWORDS:
        text = (p.get("title", "") + " " + p.get("description", "")).lower()
        return any(kw in text for kw in KEYWORDS)
    return True


async def bot_listener(http: httpx.AsyncClient):
    """Poll Telegram for /pause and /resume commands."""
    global paused, scoring_enabled
    offset = None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            resp = await http.get(url, params=params, timeout=35)
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip().lower()
                if chat_id != TELEGRAM_CHAT_ID:
                    continue
                if text == "/pause":
                    paused = True
                    log.info("Monitoring paused")
                    await send_telegram(http, "⏸ <b>Мониторинг на паузе.</b>\nОтправь /resume чтобы возобновить.")
                elif text == "/resume":
                    paused = False
                    log.info("Monitoring resumed")
                    await send_telegram(http, "▶️ <b>Мониторинг возобновлён.</b>")
                elif text == "/score_on":
                    scoring_enabled = True
                    await send_telegram(http, "🎯 Скоринг включён — приходят только заказы с score ≥ 60")
                elif text == "/score_off":
                    scoring_enabled = False
                    await send_telegram(http, "📋 Скоринг выключен — приходят все заказы")
                elif text == "/status":
                    state = "⏸ на паузе" if paused else "✅ активен"
                    await send_telegram(http, f"Статус: {state}\nИнтервал: {POLL_INTERVAL}с\nКатегории: {PARENT_CATEGORY_IDS}")
        except Exception as e:
            log.error("Bot listener error: %s", e)
            await asyncio.sleep(5)


async def save_project(pg: asyncpg.Connection, p: dict, score: int | None = None, reason: str = ""):
    await pg.execute("""
        INSERT INTO projects (id, title, description, price, price_max, category_id, parent_cat_id,
                              username, hired_pct, offers, time_left, url, score, score_reason)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        ON CONFLICT (id) DO NOTHING
    """,
        p.get("id"), p.get("title"), p.get("description"), p.get("price"),
        p.get("possible_price_limit"),
        p.get("category_id"), p.get("parent_category_id"),
        p.get("username"), p.get("user_hired_percent"), p.get("offers"),
        p.get("time_left"), KWORK_URL.format(id=p.get("id")),
        score, reason
    )


async def run():
    global paused
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    pg = await asyncpg.connect(PG_DSN)
    api = KworkApi()
    await api.connect()

    async with httpx.AsyncClient(timeout=15) as http:
        log.info("FreelanceRadar started. Poll interval: %ds, categories: %s",
                 POLL_INTERVAL, PARENT_CATEGORY_IDS or "all")
        await send_telegram(http, "🟢 <b>FreelanceRadar запущен</b>\nКоманды: /pause /resume /status")

        asyncio.create_task(bot_listener(http))

        while True:
            if not paused:
                try:
                    all_projects = []
                    for page in range(1, 11):
                        page_projects = await api.get_projects(categories=",".join(str(x) for x in PARENT_CATEGORY_IDS) if PARENT_CATEGORY_IDS else "", page=page)
                        if not page_projects:
                            break
                        all_projects.extend(page_projects)
                        results = [await redis.sismember("fr:seen_ids", str(p.get("id"))) for p in page_projects]
                        all_known = all(results)
                        if all_known and page >= MIN_PAGES:
                            log.info("All known on page %d, stopping", page)
                            break
                    new_projects = []
                    new_total = 0
                    for p in all_projects:
                        pid = str(p.get("id"))
                        if not await redis.sismember("fr:seen_ids", pid):
                            if matches_filter(p):
                                new_total += 1
                                await save_project(pg, p)
                                new_projects.append(p)
                            await redis.sadd("fr:seen_ids", pid)
                            await redis.expire("fr:seen_ids", 86400 * 7)
                    if new_projects:
                        await send_telegram(http, f"📋 <b>Новых заказов: {len(new_projects)}</b>")
                        for p in new_projects:
                            await send_telegram(http, format_project(p))
                            await asyncio.sleep(0.3)
                    log.info("Checked %d projects, %d new", len(all_projects), new_total)
                except Exception as e:
                    log.error("Error: %s | type: %s", e, type(e).__name__, exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
