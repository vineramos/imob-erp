from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base
from app.domains.contracts import models as contracts_models  # noqa: F401
from app.domains.finance import advanced_models as finance_advanced_models  # noqa: F401
from app.domains.finance import bank_models as finance_bank_models  # noqa: F401
from app.domains.finance import core_models as finance_core_models  # noqa: F401
from app.domains.finance import models as finance_models  # noqa: F401
from app.domains.finance import treasury_models as finance_treasury_models  # noqa: F401
from app.domains.foundation import models as foundation_models  # noqa: F401
from app.domains.inspections import models as inspection_models  # noqa: F401
from app.domains.leases import models as lease_models  # noqa: F401
from app.domains.maintenance import models as maintenance_models  # noqa: F401
from app.domains.portfolio import bank_models as portfolio_bank_models  # noqa: F401
from app.domains.portfolio import models as portfolio_models  # noqa: F401
from app.domains.portfolio import profile_models as portfolio_profile_models  # noqa: F401

config = context.config
settings = get_settings()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if settings.database_url:
    database_url = settings.database_url
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
