import sqlite3

from a2a_workbench.core.store.db import Database


async def test_missing_nullable_columns_are_added(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE workspace (id VARCHAR(32) PRIMARY KEY, name VARCHAR(200))")
    con.execute(
        "CREATE TABLE agent (id VARCHAR(32) PRIMARY KEY, workspace_id VARCHAR(32),"
        " name VARCHAR(200), base_url VARCHAR(2000), card JSON, signature_status VARCHAR(20))"
    )
    con.commit()
    con.close()
    db = Database(f"sqlite+aiosqlite:///{path}")
    await db.migrate()
    await db.dispose()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(agent)")}
    assert {"extended_card", "selected_interface_url", "card_path"} <= cols
