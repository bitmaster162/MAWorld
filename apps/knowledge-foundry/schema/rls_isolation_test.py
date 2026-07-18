"""Destructive RLS acceptance for a dedicated local Knowledge Foundry test DB.

This script drops and recreates the ``public`` schema.  It refuses to connect
unless all safety gates below are satisfied; credentials are read from an
environment DSN and never accepted on the command line.
"""
from __future__ import annotations

import ipaddress
import os
import sys
import uuid
from pathlib import Path


CONFIRMATION = "DROP_PUBLIC_SCHEMA_IN_DEDICATED_MAWORLD_RLS_TEST_DB"
CLUSTER_CONFIRMATION = "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER"
MAX_MIGRATION_BYTES = 2 * 1024 * 1024
HERE = Path(__file__).resolve().parent
MIGRATIONS = (
    HERE / "001_intake_core_v1_1.sql",
    HERE / "002_rls_roles.sql",
    HERE / "003_atomic_intake.sql",
)


def _migration_text(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if resolved.parent != HERE or resolved.name not in {item.name for item in MIGRATIONS}:
        raise RuntimeError("migration path escaped the fixed schema directory")
    if resolved.stat().st_size > MAX_MIGRATION_BYTES:
        raise RuntimeError("migration exceeds the acceptance size limit")
    return resolved.read_text(encoding="utf-8")


def _configuration():
    if os.environ.get("KF_RLS_TEST_ALLOW_DESTRUCTIVE") != CONFIRMATION:
        raise RuntimeError("destructive RLS acceptance confirmation is absent")
    if os.environ.get("KF_RLS_TEST_ALLOW_CLUSTER_ROLE_RESET") != CLUSTER_CONFIRMATION:
        raise RuntimeError("disposable PostgreSQL cluster role-reset confirmation is absent")
    dsn = os.environ.get("KF_RLS_ADMIN_DATABASE_URL")
    if not dsn:
        raise RuntimeError("KF_RLS_ADMIN_DATABASE_URL is required")
    try:
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
    except ImportError as error:
        raise RuntimeError("pinned psycopg3 runtime is required") from error
    values = conninfo_to_dict(dsn)
    host = values.get("host")
    database = values.get("dbname", "")
    for override in ("hostaddr", "service", "options", "target_session_attrs"):
        if values.get(override):
            raise RuntimeError(f"RLS destructive acceptance forbids DSN override: {override}")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("RLS destructive acceptance is restricted to explicit loopback")
    prefix = "maworld_rls_test_"
    suffix = database.removeprefix(prefix)
    if not suffix or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in suffix):
        raise RuntimeError("database name must be a safe maworld_rls_test_* identifier")
    return psycopg, dsn, database


def main() -> int:
    psycopg, dsn, expected_database = _configuration()
    connection = psycopg.connect(dsn, autocommit=False)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT current_database(), inet_server_addr()::text, pg_is_in_recovery(), role.rolsuper, "
            "       (SELECT count(*) FROM pg_catalog.pg_database AS database "
            "         WHERE database.datname NOT IN "
            "               ('template0', 'template1', 'postgres', current_database())) "
            "FROM pg_catalog.pg_roles AS role WHERE role.rolname = SESSION_USER"
        )
        (
            actual_database,
            server_address,
            in_recovery,
            is_superuser,
            other_user_databases,
        ) = cursor.fetchone()
        if actual_database != expected_database:
            raise RuntimeError("connected database does not match the guarded DSN")
        if server_address is None or not ipaddress.ip_address(server_address).is_loopback:
            raise RuntimeError("actual PostgreSQL server address is not loopback")
        if in_recovery:
            raise RuntimeError("destructive acceptance refuses a recovery/standby server")
        if not is_superuser:
            raise RuntimeError("destructive acceptance requires the disposable DB superuser")
        if other_user_databases:
            raise RuntimeError("destructive acceptance requires a disposable PostgreSQL cluster")
        # Admin-only reset/seed path. Never point this test at a shared database.
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cursor.execute("DROP ROLE IF EXISTS kf_ingest_owner;")
        cursor.execute("DROP ROLE IF EXISTS kf_runtime;")
        for migration in MIGRATIONS:
            cursor.execute(_migration_text(migration))
        project_a, project_b = uuid.uuid4(), uuid.uuid4()
        cursor.execute(
            "INSERT INTO project(project_id,slug) VALUES(%s,'proj-A'),(%s,'proj-B')",
            (project_a, project_b),
        )
        blob = uuid.uuid4()
        cursor.execute(
            "INSERT INTO raw_blob(blob_id,sha256,byte_size,storage_uri) VALUES(%s,%s,27,'cas://x')",
            (blob, "a" * 64),
        )
        occurrence_b = uuid.uuid4()
        cursor.execute(
            "INSERT INTO artifact_occurrence"
            "(occurrence_id,project_id,source_system_id,source_native_id,blob_id) "
            "VALUES(%s,%s,'lf','A::f.md',%s)",
            (uuid.uuid4(), project_a, blob),
        )
        cursor.execute(
            "INSERT INTO artifact_occurrence"
            "(occurrence_id,project_id,source_system_id,source_native_id,blob_id) "
            "VALUES(%s,%s,'lf','B::f.md',%s)",
            (occurrence_b, project_b, blob),
        )
        connection.commit()

        def scoped(query: str, project_ids: str | None):
            try:
                cursor.execute("SET LOCAL ROLE kf_runtime")
                if project_ids is not None:
                    cursor.execute(
                        "SELECT set_config('app.project_ids', %s, true)",
                        (project_ids,),
                    )
                cursor.execute(query)
                row = cursor.fetchone()
                connection.rollback()
                return row, None
            except Exception as error:
                connection.rollback()
                return None, error

        results: dict[str, bool] = {}
        occurrences = (
            "SELECT count(*), coalesce(string_agg(source_native_id,','),'') "
            "FROM artifact_occurrence"
        )
        joined = (
            "SELECT count(*) FROM raw_blob b "
            "JOIN artifact_occurrence o ON o.blob_id=b.blob_id"
        )
        row_a, _ = scoped(occurrences, str(project_a))
        row_b, _ = scoped(occurrences, str(project_b))
        row_none, _ = scoped(occurrences, None)
        scoped(occurrences, str(project_a))
        row_reused, _ = scoped(occurrences, None)
        join_a, _ = scoped(joined, str(project_a))
        join_none, _ = scoped(joined, None)
        results["A scope sees only A"] = row_a == (1, "A::f.md")
        results["B scope sees only B"] = row_b == (1, "B::f.md")
        results["missing scope sees zero rows"] = row_none == (0, "")
        results["pool reuse does not leak scope"] = row_reused == (0, "")
        results["blob is reachable only through authorized occurrence"] = (
            join_a == (1,) and join_none == (0,)
        )
        injected, injection_error = scoped(
            occurrences, f"{project_a}','{project_b}"
        )
        results["crafted scope cannot widen access"] = (
            injection_error is not None or injected == (0, "")
        )

        cursor.execute(
            "DELETE FROM artifact_occurrence WHERE occurrence_id=%s",
            (occurrence_b,),
        )
        connection.commit()
        after_delete, _ = scoped(occurrences, str(project_b))
        results["deletion removes B linkage"] = after_delete == (0, "")
        cursor.execute("SELECT count(*) FROM artifact_occurrence")
        results["admin seed path sees remaining row"] = cursor.fetchone() == (1,)
        connection.rollback()

        for name, passed in results.items():
            print(("PASS" if passed else "FAIL"), "|", name)
        return 0 if all(results.values()) else 1
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        raise SystemExit(2)
