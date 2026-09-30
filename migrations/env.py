from logging.config import fileConfig

from alembic import context

from kyvon.config import Settings
from kyvon.db import Base, make_engine
from kyvon.models import *  # noqa: F401,F403  (registers tables on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # Explicit URL (e.g. from the CLI or tests) wins; otherwise use KYVON settings.
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    return Settings.from_env(load_dotenv_file=True, require_api_key=False).db_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(get_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
