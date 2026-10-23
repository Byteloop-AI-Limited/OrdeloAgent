---
name: ordelo-sql-test-db
description: Start, stop, reset and run the OrdeloAgent isolated-database SQL tests (tests/sql) against a throwaway local Postgres. Use when SQL files under ordelo_datamodels/ change or the user asks to run SQL tests.
---

# OrdeloAgent SQL tests on a throwaway local Postgres

The tests in `tests/sql/` run the REAL SQL files from `ordelo_datamodels/` against a Postgres and are skipped unless `ORDELO_TEST_DB_URI` is set. They reset the `public` schema, so the database must be a throwaway. `tests/sql/conftest.py` refuses any host except localhost / 127.0.0.1 / ::1 / a unix socket. Never point this at Supabase or any shared database. Preparing or testing SQL does not authorise applying it anywhere (see the `database-operations` skill).

This skill uses its OWN cluster (separate data directory, port 5544), so it never touches the owner's everyday Postgres (Homebrew service, Postgres.app or other) on 5432.

## Settings (use these names in every command)

```bash
export PGTEST_DIR="$HOME/.cache/ordelo-pgtest"      # data directory of the throwaway cluster
export PGTEST_PORT=5544
export ORDELO_TEST_DB_URI="postgresql://postgres@localhost:$PGTEST_PORT/postgres"
```

## 0. Find the Postgres binaries (once per shell)

The owner has Postgres installed on the Mac, possibly more than one (Homebrew and/or Postgres.app). Pick ONE set of binaries (any version 14+ works; 16 is what was verified).

```bash
which initdb pg_ctl psql                    # on PATH already?
ls /opt/homebrew/opt | grep -i postgres     # Homebrew (Apple silicon), e.g. postgresql@16
ls /usr/local/opt | grep -i postgres        # Homebrew (Intel)
ls /Applications/Postgres.app/Contents/Versions 2>/dev/null   # Postgres.app
```

Put the chosen `bin` directory first on PATH, for example:

```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
# or: export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
initdb --version && pg_ctl --version
```

Do not use `brew services` for this cluster, and do not stop the owner's own Postgres. If port 5544 is busy (`lsof -nP -iTCP:5544 -sTCP:LISTEN`), choose another `PGTEST_PORT` and update the URI.

## 1. Create the cluster (once)

```bash
initdb -D "$PGTEST_DIR" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null && echo created
```

If `$PGTEST_DIR` already exists, skip this step.

## 2. Start

```bash
pg_ctl -D "$PGTEST_DIR" -o "-p $PGTEST_PORT -c listen_addresses=localhost" -l "$PGTEST_DIR/server.log" -w start
pg_isready -h localhost -p $PGTEST_PORT          # expect: accepting connections
```

## 3. Run the tests (from the repo root, with the repo `.venv`)

The repo `.venv` already has `pytest` and `psycopg`. On macOS use it directly:

```bash
cd /Users/basavaraj/bloop/OrdeloAgent
source .venv/bin/activate
export PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1
pytest tests/sql -q -p no:cacheprovider                                   # all SQL tests
pytest tests/sql/test_restaurant_ready_adjust_notices_sql.py -q -p no:cacheprovider      # one file
pytest tests/sql -q -p no:cacheprovider -k receipt_snapshot -v            # by name
```

If `import psycopg` fails: `uv pip install "psycopg[binary]"` in the `.venv`.

The fixtures re-apply the migration files in the order listed in `tests/sql/conftest.py` (`MIGRATION_FILES`). A NEW SQL file must be added there or the tests will not see it.

## 4. Inspect, reset, stop

```bash
psql "$ORDELO_TEST_DB_URI"                       # look around (throwaway data)
psql "$ORDELO_TEST_DB_URI" -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'   # reset the schema (tests also do this)
tail -n 50 "$PGTEST_DIR/server.log"              # server log
pg_ctl -D "$PGTEST_DIR" status                   # running?
pg_ctl -D "$PGTEST_DIR" -m fast stop            # stop
```

Full wipe (destroys only this throwaway cluster; confirm `$PGTEST_DIR` is the path above first):

```bash
pg_ctl -D "$PGTEST_DIR" -m fast stop; rm -rf "$PGTEST_DIR"
```

## 5. Cloud sandbox variant (no Postgres on the machine)

When the work happens in the Claude cloud container instead (no access to the Mac's Postgres): the container has Postgres 16 (`service postgresql start`, then `su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'pw'\""`), tar `tests/sql tests/__init__.py ordelo_datamodels` on the device, stage the tarball, extract under a scratch dir, create a venv with `pip install "psycopg[binary]" pytest`, set `ORDELO_TEST_DB_URI=postgresql://postgres:pw@localhost:5432/postgres` and `PYTHONPATH` to the scratch dir, and run `pytest tests/sql`. Stop the service afterwards, and delete any temporary files left in the repo.

## Reporting

Label the evidence **isolated database** (not live Supabase, not live Telegram). Report the pass/fail counts and the exact failing test names.

Known result (23 Oct 2026, cloud container, Postgres 16): 360 passed, 2 failed. The two failures are `test_restaurant_notices_script_sql.py::test_stage0_wipes_only_strk_test_rows_in_every_table` and `::test_stage0_copies_the_linked_chat_to_strk_only_once`. They fail identically on the committed HEAD SQL, so they were not caused by that day's change; the cause was not found (the cloud run packaged only `tests/sql` and `ordelo_datamodels`, so check them first on the Mac with the full repo). Treat any NEW failure as real, and compare against this list before blaming a change.
