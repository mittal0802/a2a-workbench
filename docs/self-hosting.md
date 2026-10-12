# Self-hosting

The Workbench is a single process: the web UI, the API, the webhook receiver and the database migrations. Run it where your agents are reachable.

## Docker

```bash
docker run -d -p 127.0.0.1:8484:8484 -v a2aw:/data ghcr.io/mittal0802/a2a-workbench
```

The image runs as an unprivileged user (UID 10001), keeps its state in the `/data` volume, includes Postgres support and reports its health on `/api/health`. Images are published for `linux/amd64` and `linux/arm64`, tagged with the version (`1.0.0`, `1.0`) and `latest`.

## Docker Compose with Postgres

The repository's [`docker-compose.yml`](https://github.com/mittal0802/a2a-workbench/blob/main/docker-compose.yml) runs the Workbench on Postgres. Put a password in a `.env` file next to it, then start it:

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" > .env
docker compose up -d
```

## Upgrades and migrations

The schema is migrated automatically on start; concurrent starts are safe (Postgres advisory lock, SQLite immediate transaction). To check or apply it yourself:

```bash
a2a-workbench db current --json
a2a-workbench db upgrade
```

Databases created by versions before 1.0 are upgraded in place, keeping their data. Back up before upgrading: copy `workbench.db` with `sqlite3 workbench.db ".backup backup.db"`, or use `pg_dump` for Postgres.

## Exposing it

The server answers only to `localhost`, `127.0.0.1`, `::1` and its bind address, and rejects cross-site `Origin`s (DNS-rebinding protection). To open it under another name, set `A2AW_ALLOWED_HOSTS`. These checks only stop DNS rebinding from web pages; they are not access control. The Workbench has no sign-in of its own, so anyone who can reach its port can use it and the credentials it stores: publish the port on `127.0.0.1` only (as above), or put it behind your own authentication. So agents on other machines can deliver push notifications, set `A2AW_PUBLIC_BASE_URL` to an address they can reach.

## Keys

Stored credentials are encrypted with `A2AW_SECRET_KEY`, or with a key generated in `<home>/secret.key`. Keep that key with your backups: without it, stored credentials cannot be read. All settings are in the [configuration reference](reference/configuration.md).
