import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from .config import load_config
from .handlers import Sessions, router
from .ingest import ingest_archive
from .llm import LLM
from .storage import Store


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    store = Store(cfg.db_path)
    llm = LLM(cfg)
    await ingest_archive(cfg.archive_dir, store, llm)

    bot = Bot(cfg.tg_token)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Що я вмію"),
        BotCommand(command="docs", description="Усі документи"),
        BotCommand(command="my", description="Мої документи"),
    ])
    await dp.start_polling(bot, store=store, llm=llm, sessions=Sessions(), cfg=cfg)


if __name__ == "__main__":
    asyncio.run(main())
