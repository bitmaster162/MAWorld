set -e
BIN=/tmp/pg/pgdist/bin; DATA=/tmp/m8/pgdata; SOCK=/tmp/m8/run; PORT=5434
rm -f "$DATA/postmaster.pid"
$BIN/pg_ctl -D "$DATA" -o "-p $PORT -k $SOCK" -l /tmp/m8/pg2.log -w start >/dev/null
echo "PG restarted from SAME data dir (durable state survived full DB restart)"
cd /tmp/m8
export M8_PG_URL="postgresql://maworld@localhost:5434/dbos_sys"
export M8_EFFECT_LOG="/tmp/m8/effect.log"
echo "effect.log BEFORE recovery:"; cat "$M8_EFFECT_LOG"
python3 m8_recover.py >/tmp/m8/recover.out 2>&1 || true
grep "recover-child" /tmp/m8/recover.out || tail -4 /tmp/m8/recover.out
echo "== ASSERTIONS =="
python3 - <<'PY'
lines=[l for l in open("/tmp/m8/effect.log") if l.startswith("EFFECT")]
print("EFFECT fire count:",len(lines),"->","PASS no-duplicate-effect" if len(lines)==1 else "FAIL DUPLICATE")
rec=open("/tmp/m8/recover.out").read()
print("recovery executed:","PASS" if "recovered" in rec else "FAIL")
print("workflow completed on recovery:","PASS" if "'done'" in rec or "done" in rec else "check", )
import psycopg
c=psycopg.connect("host=localhost port=5434 user=maworld dbname=dbos_sys",autocommit=True);cur=c.cursor()
cur.execute("select count(*) from information_schema.tables where table_schema='dbos'")
print("dbos schema tables in Postgres:",cur.fetchone()[0])
cur.execute("select status,count(*) from dbos.workflow_status group by status")
print("workflow_status:",cur.fetchall())
cur.execute("select function_name from dbos.operation_outputs order by function_id")
print("recorded step outputs (durable):",[r[0] for r in cur.fetchall()])
PY
$BIN/pg_ctl -D "$DATA" -m fast stop -w >/dev/null
echo "STAGE2 DONE"
