# DEPLOY.md

The bot is a pure gateway client (Shape A per CLAUDE.md §13.1): two
containers, `superiorspork` (the bot) and `spork-db` (Postgres 17), on the
compose project's private network. No ports are published, nothing is routed
through Traefik, and there is no HTTP surface.

Secrets never enter the image: `config.py` is bind-mounted read-only at
runtime and `.dockerignore` excludes it from the build context.

## First run

```bash
cp config.example.py config.py   # fill TOKEN; set both DSNs to
                                 # postgresql://spork:<password>@db:5432/spork
cp .env.example .env             # set POSTGRES_PASSWORD=<same password>
chmod 600 config.py .env
setfacl -m u:10001:r config.py   # the container runs as UID 10001 and needs
                                 # read on the bind-mounted config
docker compose up -d --build
```

`TESTING` in `config.py` picks which token/prefix pair is used; the DSNs both
point at the container DB, so either mode works inside compose. Note that
means the DB is only reachable from inside the compose network — running the
bot directly on the host will not find it (intentional; use the container).

## Everyday

```bash
docker compose logs -f bot        # startup, extension loads, tracebacks
docker compose exec db psql -U spork spork   # poke the database
docker compose stop               # graceful; should return in ~1-2s
docker compose up -d              # start again
```

## Update

```bash
git pull
docker compose up -d --build bot
```

## Roll back

```bash
git checkout <last-good-ref>
docker compose up -d --build bot
```

Database data survives all of the above in the `spork-db-data` volume.
Dropping the database is `docker compose down -v` — that deletes the volume,
so don't, unless you mean it.
