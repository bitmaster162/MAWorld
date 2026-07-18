"""Expose external PostgreSQL RLS acceptance to the active test inventory."""
from __future__ import annotations

import os
import sys


CONFIRMATION = "DROP_PUBLIC_SCHEMA_IN_DEDICATED_MAWORLD_RLS_TEST_DB"
CLUSTER_CONFIRMATION = "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER"
if (
    os.environ.get("KF_RLS_TEST_ALLOW_DESTRUCTIVE") != CONFIRMATION
    or os.environ.get("KF_RLS_TEST_ALLOW_CLUSTER_ROLE_RESET") != CLUSTER_CONFIRMATION
    or not os.environ.get("KF_RLS_ADMIN_DATABASE_URL")
):
    print(
        "SKIP dedicated PostgreSQL RLS acceptance: set the explicit destructive "
        "database/cluster confirmations and a loopback maworld_rls_test_* admin DSN"
    )
    raise SystemExit(0)

from rls_isolation_test import main

raise SystemExit(main())
