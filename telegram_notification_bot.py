import os, re, logging, asyncio, yaml
from dataclasses import dataclass
from typing import List, Pattern, Dict, Any
from jinja2 import Template
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# env из файла для локального запуска; в контейнере переменные придут из compose
load_dotenv(override=False)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notification_bot")

# suppress noisy httpx/telegram logs
for noisy in ["httpx", "telegram", "apscheduler", "urllib3"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# обязательные переменные
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    SUPERCHAT_ID = int(os.environ["SUPERCHAT_ID"])
except KeyError as e:
    raise SystemExit(f"Нет обязательной переменной окружения: {e}")

# опциональные источники: группа и/или канал
SOURCE_GROUP_ID = os.environ.get("SOURCE_GROUP_ID")
if SOURCE_GROUP_ID:
    SOURCE_GROUP_ID = int(SOURCE_GROUP_ID)

SOURCE_CHANNEL_ID = os.environ.get("SOURCE_CHANNEL_ID")
if SOURCE_CHANNEL_ID:
    SOURCE_CHANNEL_ID = int(SOURCE_CHANNEL_ID)

RULES_FILE = os.environ.get("RULES_FILE", "/rules.yml")

@dataclass
class Rule:
    pattern: Pattern
    topic_id: int
    template: Template

def load_rules(path: str) -> List[Rule]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    rules: List[Rule] = []
    for i, r in enumerate(raw):
        pat = re.compile(r["pattern"], re.MULTILINE)
        topic_id = int(r["topic_id"])
        tpl = Template(r["template"])
        rules.append(Rule(pat, topic_id, tpl))
        log.info("rule %d -> topic %s", i, topic_id)
    if not rules:
        log.warning("rules file is empty: %s", path)
    return rules

RULES = load_rules(RULES_FILE)

async def match_and_send(text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not text:
        return
    for rule in RULES:
        m = rule.pattern.search(text)
        if not m:
            continue
        data: Dict[str, Any] = m.groupdict()
        data["_raw"] = text
        out_text = rule.template.render(**data)
        try:
            await context.bot.send_message(
                chat_id=SUPERCHAT_ID,
                text=out_text,
                message_thread_id=rule.topic_id,
                parse_mode=None,
                disable_web_page_preview=True,
            )
            log.info("sent -> topic %s", rule.topic_id)
        except Exception as e:
            log.exception("send failed: %s", e)
        break  # одно совпадение на сообщение

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.channel_post
    if not msg:
        return
    log.info("channel_post chat=%s text_len=%s caption_len=%s", msg.chat_id, len(msg.text or ""), len(msg.caption or ""))
    # если указан SOURCE_CHANNEL_ID — фильтруем по нему; если нет — принимаем все посты каналов
    if SOURCE_CHANNEL_ID is not None and msg.chat_id != SOURCE_CHANNEL_ID:
        return
    text = msg.text or msg.caption or ""
    await match_and_send(text, context)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # посты из каналов только
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_post))
    log.info(
        "started. source_group=%s source_channel=%s target_superchat=%s",
        SOURCE_GROUP_ID, SOURCE_CHANNEL_ID, SUPERCHAT_ID,
    )
    await app.initialize()
    await app.start()
    try:
        await app.updater.start_polling(allowed_updates=["channel_post"])
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())