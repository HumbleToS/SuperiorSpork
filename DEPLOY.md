# DEPLOY.md

The bot is a pure gateway client (Shape A per CLAUDE.md §13.1): two
containers, `superiorspork` (the bot) and `spork-db` (Postgres 17), on the
compose project's private network. No ports are published, nothing is routed
through Traefik, and there is no HTTP surface.

**`config.py` is the single secrets file.** It is bind-mounted read-only at
runtime, `.dockerignore` excludes it from the build context, and there is no
`.env` — the Postgres password's one home is the DSN inside `config.py`.

## First run

```bash
cp config.example.py config.py   # fill TOKEN; set both DSNs to
                                 # postgresql://spork:<password>@db:5432/spork
                                 # (generate: openssl rand -hex 24)
chmod 600 config.py
setfacl -m u:10001:r config.py   # the container runs as UID 10001 and needs
                                 # read on the bind-mounted config
POSTGRES_PASSWORD=<same password> docker compose up -d --build
```

Postgres only reads `POSTGRES_PASSWORD` the very first time its data volume
is created; after that the inline variable is unnecessary and a plain
`docker compose up -d` is all you ever type. If you ever delete the
`spork-db-data` volume, run the inline form again with the password from
`config.py`.

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
