"""Alembic environment: migrates the connection handed over in ``config.attributes``."""

from alembic import context

from a2a_workbench.core.store.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
