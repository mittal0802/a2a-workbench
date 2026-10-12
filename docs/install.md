# Install

=== "pipx"

    ```bash
    pipx install a2a-workbench
    a2a-workbench serve --open
    ```

=== "uv"

    ```bash
    uv tool install a2a-workbench      # or once, without installing: uvx a2a-workbench serve --open
    a2a-workbench serve --open
    ```

=== "Docker"

    ```bash
    docker run -p 127.0.0.1:8484:8484 -v a2aw:/data ghcr.io/mittal0802/a2a-workbench
    ```

The web UI opens on <http://127.0.0.1:8484>. The package needs Python 3.12 or newer.

State (database, encryption key, uploads) lives in `~/.a2a-workbench/`; change it with `A2AW_HOME`. To use Postgres instead of SQLite, install the extra and set the URL:

```bash
pipx install 'a2a-workbench[postgres]'
export A2AW_DATABASE_URL=postgresql+asyncpg://user:password@host/db
```

Schema migrations run automatically when the server or a command starts, including the upgrade of databases created before 1.0. See [Self-hosting](self-hosting.md) and [Configuration](reference/configuration.md).
