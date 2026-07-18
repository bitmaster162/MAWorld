set -e
BIN=/tmp/pg/pgdist/bin; DATA=/tmp/m8/pgdata; SOCK=/tmp/m8/run; PORT=5434
rm -rf "$DATA" "$SOCK"; mkdir -p "$SOCK"
$BIN/initdb -D "$DATA" -U maworld -A trust --no-sync >/tmp/m8/initdb.log 2>&1
echo "listen_addresses='localhost'" >> "$DATA/postgresql.conf"
$BIN/pg_ctl -D "$DATA" -o "-p $PORT -k $SOCK" -l /tmp/m8/pg.log -w start >/dev/null
echo "PG up (fresh cluster on :$PORT)"
python3 - <<'PY'
import psycopg
c=psycopg.connect("host=localhost port=5434 user=maworld dbname=postgres",autocommit=True);cur=c.cursor()
for db in ("maworld","dbos_sys"):
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s",(db,))
    if not cur.fetchone(): cur.execute(f'CREATE DATABASE {db}')
cur.execute("select version()");print("createdb ok;",cur.fetchone()[0][:34])
b="/sessions/zealous-elegant-albattani/mnt/MAWorld/apps/knowledge-foundry/schema/"
c2=psycopg.connect("host=localhost port=5434 user=maworld dbname=maworld",autocommit=True);cur2=c2.cursor()
for n in ("001_intake_core_v1_1.sql","002_rls_roles.sql"):
    sql=open(b+n).read()
    try: cur2.execute(sql); print(f"  migration {n[:3]} applied ({len(sql)}B)")
    except Exception as e: print(f"  migration {n[:3]} ERR:",str(e)[:120])
cur2.execute("select count(*) from information_schema.tables where table_schema='public'")
print("  maworld public tables:",cur2.fetchone()[0])
PY
cd /tmp/m8
export M8_PG_URL="postgresql://maworld@localhost:5434/dbos_sys"
export M8_EFFECT_LOG="/tmp/m8/effect.log"; rm -f "$M8_EFFECT_LOG"
echo "order-M8FIXED" > /tmp/m8/idem.txt
set +e
python3 m8_crash.py "order-M8FIXED" >/tmp/m8/crash.out 2>&1
echo "crash child exit: $? (expect 137)"; set -e
echo "effect.log after crash:"; cat "$M8_EFFECT_LOG" 2>/dev/null || echo "(none)"
tail -3 /tmp/m8/crash.out
$BIN/pg_ctl -D "$DATA" -m fast stop -w >/dev/null
echo "STAGE1 DONE (PG stopped; durable state on disk)"
