set -e
BIN=/tmp/pg/pgdist/bin; DATA=/tmp/rls/pgdata; SOCK=/tmp/rls/run; PORT=5435
rm -rf "$DATA" "$SOCK"; mkdir -p "$SOCK"
$BIN/initdb -D "$DATA" -U kf_admin -A trust --no-sync >/tmp/rls/initdb.log 2>&1
echo "listen_addresses='localhost'" >> "$DATA/postgresql.conf"
$BIN/pg_ctl -D "$DATA" -o "-p $PORT -k $SOCK" -l /tmp/rls/pg.log -w start >/dev/null
python3 - <<'PY'
import psycopg
A="host=localhost port=5435 user=kf_admin dbname=postgres"
c=psycopg.connect(A,autocommit=True); cur=c.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname='kf'");
if not cur.fetchone(): cur.execute("CREATE DATABASE kf")
c.close()
adm=psycopg.connect("host=localhost port=5435 user=kf_admin dbname=kf",autocommit=True); a=adm.cursor()
# table with FORCE RLS + policy scoped by app.project_ids
a.execute("""CREATE TABLE artifact_occurrence(id serial primary key, project_id text not null, data text)""")
a.execute("ALTER TABLE artifact_occurrence ENABLE ROW LEVEL SECURITY")
a.execute("ALTER TABLE artifact_occurrence FORCE ROW LEVEL SECURITY")
a.execute("""CREATE POLICY tenant ON artifact_occurrence
             USING (project_id = current_setting('app.project_ids', true))
             WITH CHECK (project_id = current_setting('app.project_ids', true))""")
# NON-superuser, NON-owner runtime role WITH the INSERT grant the old role lacked
a.execute("DROP ROLE IF EXISTS kf_runtime")
a.execute("CREATE ROLE kf_runtime NOSUPERUSER NOBYPASSRLS LOGIN")
a.execute("GRANT SELECT, INSERT ON artifact_occurrence TO kf_runtime")
a.execute("GRANT USAGE, SELECT ON SEQUENCE artifact_occurrence_id_seq TO kf_runtime")
# seed rows for two tenants (as admin)
a.execute("INSERT INTO artifact_occurrence(project_id,data) VALUES ('A','a1'),('A','a2'),('B','b1')")
adm.close()

R={}; P=[0]; F=[0]
def ok(n,c,d=""):
    b=bool(c); P[0]+=b; F[0]+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# runtime role, per-request scoped transaction
rt=psycopg.connect("host=localhost port=5435 user=kf_runtime dbname=kf")
def scoped(pid, fn):
    with rt.transaction():
        rt.execute("SELECT set_config('app.project_ids', %s, true)", (pid,))  # SET LOCAL equiv
        return fn()
# isolation: scope A sees only A
def q(): return rt.execute("SELECT project_id,data FROM artifact_occurrence ORDER BY id").fetchall()
rowsA=scoped("A", q); ok("runtime scope A sees ONLY A rows", {r[0] for r in rowsA}=={"A"} and len(rowsA)==2, str(rowsA))
rowsB=scoped("B", q); ok("runtime scope B sees ONLY B rows", {r[0] for r in rowsB}=={"B"} and len(rowsB)==1, str(rowsB))
# INSERT within scope works (the grant the old role lacked)
def insA(): rt.execute("INSERT INTO artifact_occurrence(project_id,data) VALUES('A','a3')"); return True
ok("runtime can INSERT within its scope", scoped("A", insA))
ok("insert visible in scope A now 3", len(scoped("A",q))==3)
# WITH CHECK: cannot insert a row for another tenant while scoped to A
def insB_underA(): rt.execute("INSERT INTO artifact_occurrence(project_id,data) VALUES('B','evil')"); return True
try:
    scoped("A", insB_underA); ok("cross-tenant INSERT blocked by WITH CHECK", False)
except Exception as e: ok("cross-tenant INSERT blocked by WITH CHECK", "policy" in str(e).lower() or "row-level" in str(e).lower(), str(e)[:60])
# no scope set -> sees nothing (fail-closed), not everything
norows=rt.execute("SELECT count(*) FROM artifact_occurrence").fetchone(); rt.rollback()
ok("runtime with NO scope sees 0 (fail-closed)", norows[0]==0, str(norows))
rt.close()

# CONTRAST: superuser/admin BYPASSES RLS -> must NOT be the runtime role
adm=psycopg.connect("host=localhost port=5435 user=kf_admin dbname=kf",autocommit=True)
allrows=adm.execute("SELECT count(*) FROM artifact_occurrence").fetchone()[0]
ok("admin/superuser BYPASSES RLS (why prod must use kf_runtime)", allrows>=4, f"admin sees {allrows}")
adm.close()
print(f"\nTALLY RLS scoped: PASS={P[0]} FAIL={F[0]}")
import sys; sys.exit(1 if F[0] else 0)
PY
rc=$?
$BIN/pg_ctl -D "$DATA" -m fast stop -w >/dev/null 2>&1 || true
exit $rc
