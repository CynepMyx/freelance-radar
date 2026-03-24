"""FreelanceRadar — Kwork monitor with Telegram alerts."""
import asyncio
import logging
import os
import json
import re

import asyncpg
import httpx
import redis.asyncio as aioredis

from adapters.kwork import KworkApi, normalize_kwork_project
from project import Project

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("freelance-radar")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "120"))
MIN_PAGES = int(os.environ.get("MIN_PAGES", "3"))
MIN_HIRED_PCT = int(os.environ.get("MIN_HIRED_PCT", "0"))
KEYWORDS = [k.strip().lower() for k in os.environ.get("KEYWORDS", "").split(",") if k.strip()]

PARENT_CATEGORY_IDS = {int(x) for x in os.environ.get("PARENT_CATEGORY_IDS", "11").split(",") if x.strip()}
EXCLUDE_CATEGORY_IDS = {int(x) for x in os.environ.get("EXCLUDE_CATEGORY_IDS", "").split(",") if x.strip()}

PG_DSN = os.environ.get("PG_DSN", "postgresql://fr_user:change_me@postgres:5432/freelance_radar")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SCORE_THRESHOLD = int(os.environ.get("SCORE_THRESHOLD", "60"))

paused = False
scoring_enabled = bool(OPENROUTER_API_KEY)


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
- WordPress: перенос, ускорение, кеш, безопасность, настройка
- диагностика ошибок, падений, тормозов на сервере и сайте
- бэкапы, миграции, восстановление данных
- аудит сервера / сайта / безопасности

Сильный плюс:
- диагностика, аудит, поиск причины проблемы
- исправление аварии, ошибки, падения
- перенос, миграция существующей инфраструктуры

НЕ подходит:
- дизайн, верстка, создание сайта с нуля
- frontend / backend разработка как основная задача
- мобильные приложения
- 1С, бухгалтерия
- SEO, SMM, реклама, маркетинг

Шкала: 80-100 явно подходит, 60-79 скорее подходит, 40-59 пограничный, 0-39 не подходит.
Будь строгим. Отвечай ТОЛЬКО валидным JSON: {"score": <0-100>, "reason": "<одна фраза>"}
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

        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\{.*?\}", content, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object in response: {content[:100]}")
        data = json.loads(m.group())
        return int(data["score"]), data.get("reason", "")
    except Exception as e:
        log.warning("Score error: %s", e)
        return 50, "error"


def format_project(p: Project) -> str:
    desc = re.sub(r"<[^>]+>", " ", p.description).strip()
    desc = re.sub(r"\s+", " ", desc)
    if len(desc) > 3500:
        desc = desc[:3500].rsplit(" ", 1)[0] + "…"

    hours_left = p.hours_left if p.hours_left is not None else "?"
    hired_pct = p.client_hired_percent if p.client_hired_percent is not None else 0

    desc_line = f"\n📝 {desc}" if desc else ""
    score_line = f"\n🎯 Score: {p.score} — {p.score_reason}" if p.score is not None else ""

    return (
        f"🆕 <b>{p.title}</b>\n"
        f"💰 {p.budget_text}  |  📩 {p.offers}  |  ⏳ {hours_left}ч  |  🤝 {hired_pct}%"
        f"{desc_line}"
        f"{score_line}\n"
        f"🔗 <a href='{p.url}'>Открыть на {p.source.capitalize()}</a>"
    )


def matches_filter(p: Project) -> bool:
    if EXCLUDE_CATEGORY_IDS and p.category_id in EXCLUDE_CATEGORY_IDS:
        return False
    if MIN_HIRED_PCT and (p.client_hired_percent or 0) < MIN_HIRED_PCT:
        return False
    if KEYWORDS:
        text = f"{p.title} {p.description}".lower()
        return any(kw in text for kw in KEYWORDS)
    return True


async def bot_listener(http: httpx.AsyncClient):
    """Poll Telegram for commands."""
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
                    if not OPENROUTER_API_KEY:
                        await send_telegram(http, "⚠️ OpenRouter API key not configured")
                    else:
                        scoring_enabled = True
                        await send_telegram(http, "🎯 Скоринг включён")
                elif text == "/score_off":
                    scoring_enabled = False
                    await send_telegram(http, "📋 Скоринг выключен")
                elif text == "/status":
                    state = "⏸ на паузе" if paused else "✅ активен"
                    await send_telegram(http, f"Статус: {state}\nИнтервал: {POLL_INTERVAL}с\nКатегории: {PARENT_CATEGORY_IDS}")
        except Exception as e:
            log.error("Bot listener error: %s", e)
            await asyncio.sleep(5)


async def save_project(pg: asyncpg.Connection, p: Project):
    await pg.execute("""
        INSERT INTO projects (id, source, title, description, price, price_max,
                              category_id, parent_cat_id, username, hired_pct,
                              offers, time_left, url, score, score_reason)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        ON CONFLICT (id) DO NOTHING
    """,
        int(p.project_id), p.source, p.title, p.description,
        p.price_from, p.price_to,
        p.category_id, p.parent_category_id,
        p.client_username, p.client_hired_percent,
        p.offers, p.time_left_seconds,
        p.url, p.score, p.score_reason,
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
        await send_telegram(http, "🟢 <b>FreelanceRadar запущен</b>\nКоманды: /pause /resume /status /score_on /score_off")

        asyncio.create_task(bot_listener(http))

        log.info("Startup sweep: scanning pages to populate Redis...")
        cats_param = ",".join(str(x) for x in PARENT_CATEGORY_IDS) if PARENT_CATEGORY_IDS else ""
        sweep_count = 0
        for page in range(1, 100):
            try:
                raw_projects = await api.get_projects(categories=cats_param, page=page)
            except Exception as e:
                log.warning("Startup sweep page %d error: %s", page, e)
                break
            if not raw_projects or not isinstance(raw_projects, list):
                break
            for raw in raw_projects:
                p = normalize_kwork_project(raw)
                await redis.sadd("fr:seen_ids", p.project_id)
            await redis.expire("fr:seen_ids", 86400 * 7)
            sweep_count += len(raw_projects)
        log.info("Startup sweep complete: %d projects indexed", sweep_count)

        while True:
            if not paused:
                try:
                    all_projects = []
                    cats_param = ",".join(str(x) for x in PARENT_CATEGORY_IDS) if PARENT_CATEGORY_IDS else ""
                    for page in range(1, 11):
                        raw_page = await api.get_projects(categories=cats_param, page=page)
                        if not raw_page or not isinstance(raw_page, list):
                            break
                        page_projects = [normalize_kwork_project(r) for r in raw_page]
                        all_projects.extend(page_projects)
                        results = [await redis.sismember("fr:seen_ids", p.project_id) for p in page_projects]
                        if all(results) and page >= MIN_PAGES:
                            log.info("All known on page %d, stopping", page)
                            break

                    new_projects = []
                    new_total = 0
                    for p in all_projects:
                        if not await redis.sismember("fr:seen_ids", p.project_id):
                            if matches_filter(p):
                                if scoring_enabled:
                                    score, reason = await score_project(http, p.title, p.description)
                                    p.score = score
                                    p.score_reason = reason
                                    if score < SCORE_THRESHOLD:
                                        await redis.sadd("fr:seen_ids", p.project_id)
                                        await redis.expire("fr:seen_ids", 86400 * 7)
                                        continue
                                new_total += 1
                                await save_project(pg, p)
                                new_projects.append(p)
                            await redis.sadd("fr:seen_ids", p.project_id)
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
