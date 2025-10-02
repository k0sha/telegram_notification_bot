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

# обязательные переменные
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    SOURCE_GROUP_ID = int(os.environ["SOURCE_GROUP_ID"])
    SUPERCHAT_ID = int(os.environ["SUPERCHAT_ID"])
except KeyError as e:
    raise SystemExit(f"Нет переменной окружения: {e}")

RULES_FILE = os.environ.get("RULES_FILE", "/app/rules.yml")

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or msg.chat_id != SOURCE_GROUP_ID:
        return

    text = msg.text or msg.caption or ""
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

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.Caption(), handle_message))
    log.info("started. source=%s target=%s", SOURCE_GROUP_ID, SUPERCHAT_ID)
    await app.initialize()
    await app.start()
    try:
        await app.updater.start_polling(allowed_updates=["message"])
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())