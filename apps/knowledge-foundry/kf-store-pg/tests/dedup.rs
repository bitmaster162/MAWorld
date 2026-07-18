//! Ignored acceptance against a live, explicitly disposable PostgreSQL database.
//!
//! Proves atomic dedup/idempotency, immutable-metadata conflict rejection, cross-project RLS,
//! transaction rollback, concurrent deduplication, and project-context reset on pool reuse.
//! Requires migrations 001 + 002 + 003 and never runs in the default test inventory.
use kf_store_pg::{IngestObservation, IngestOutcome, MetaStore, PostgresMetaStore};
use sqlx_core::{
    pool::{Pool, PoolOptions},
    query::query,
    row::Row,
    transaction::Transaction,
};
use sqlx_postgres::{PgConnection, Postgres};
use uuid::Uuid;

const CONFIRMATION: &str = "MAWORLD_DISPOSABLE_DB_CONFIRMED";
const CLUSTER_CONFIRMATION: &str = "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER";

fn unique_hash() -> String {
    let half = Uuid::now_v7().simple().to_string();
    format!("{half}{half}")
}

fn assert_permission_denied(error: sqlx_core::Error) {
    match error {
        sqlx_core::Error::Database(database) => {
            assert_eq!(database.code().as_deref(), Some("42501"));
        }
        other => panic!("expected PostgreSQL permission denial, got {other}"),
    }
}

async fn verify_disposable_admin_connection(
    connection: &mut PgConnection,
    expected_database: &str,
) -> Result<(), sqlx_core::Error> {
    let verification = query(
        "SELECT role.rolname AS login_name,
                CURRENT_USER::text AS current_name,
                SESSION_USER::text AS session_name,
                role.rolsuper AS login_super,
                pg_catalog.current_database()::text AS database_name,
                pg_catalog.host(pg_catalog.inet_server_addr()) AS server_address,
                pg_catalog.pg_is_in_recovery() AS in_recovery,
                (
                    SELECT pg_catalog.count(*)
                      FROM pg_catalog.pg_database AS database
                     WHERE database.datname NOT IN (
                           'template0', 'template1', 'postgres',
                           pg_catalog.current_database()
                       )
                ) AS other_user_databases
           FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = SESSION_USER",
    )
    .fetch_optional(&mut *connection)
    .await?
    .ok_or_else(|| {
        sqlx_core::Error::Protocol(
            "disposable PostgreSQL administrator is absent from pg_roles".to_owned(),
        )
    })?;
    let login_name: String = verification.try_get("login_name")?;
    let current_name: String = verification.try_get("current_name")?;
    let session_name: String = verification.try_get("session_name")?;
    let actual_database: String = verification.try_get("database_name")?;
    let server_address: Option<String> = verification.try_get("server_address")?;
    let in_recovery: bool = verification.try_get("in_recovery")?;
    let is_superuser: bool = verification.try_get("login_super")?;
    let other_user_databases: i64 = verification.try_get("other_user_databases")?;
    let server_is_loopback = server_address
        .as_deref()
        .and_then(|address| address.parse::<std::net::IpAddr>().ok())
        .is_some_and(|address| address.is_loopback());
    if login_name != session_name
        || current_name != session_name
        || actual_database != expected_database
        || !server_is_loopback
        || in_recovery
        || !is_superuser
        || other_user_databases != 0
    {
        return Err(sqlx_core::Error::Protocol(
            "admin connection escaped the disposable target boundary".to_owned(),
        ));
    }
    Ok(())
}

fn input(
    project_id: Uuid,
    source_native_id: &str,
    source_revision_key: &str,
    sha256: &str,
    storage_uri: &str,
) -> IngestObservation {
    IngestObservation {
        occurrence_id: Uuid::now_v7(),
        version_id: Uuid::now_v7(),
        project_id,
        source_system_id: "acceptance".into(),
        source_native_id: source_native_id.into(),
        source_revision_key: source_revision_key.into(),
        sha256: sha256.into(),
        byte_size: 27,
        storage_uri: storage_uri.into(),
    }
}

async fn set_runtime_scope(transaction: &mut Transaction<'_, Postgres>, project_id: Uuid) {
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut **transaction)
        .await
        .expect("set local runtime role");
    let row = query(
        "SELECT pg_catalog.set_config('app.project_ids', $1, true) AS project_context,
                pg_catalog.set_config('lock_timeout', '5s', true) AS lock_timeout,
                pg_catalog.set_config('statement_timeout', '30s', true) AS statement_timeout",
    )
    .bind(project_id.to_string())
    .fetch_one(&mut **transaction)
    .await
    .expect("set local project context");
    let applied: String = row
        .try_get("project_context")
        .expect("read applied context");
    assert_eq!(applied, project_id.to_string());
}

async fn invoke_atomic(
    transaction: &mut Transaction<'_, Postgres>,
    request: &IngestObservation,
) -> Result<IngestOutcome, sqlx_core::Error> {
    let row = query(
        "SELECT blob_id, occurrence_id, version_id, parent_version_id,
                blob_created, occurrence_created, version_created
           FROM public.kf_ingest_observation($1,$2,$3,$4,$5,$6,$7,$8,$9)",
    )
    .bind(request.project_id)
    .bind(request.occurrence_id)
    .bind(request.version_id)
    .bind(&request.source_system_id)
    .bind(&request.source_native_id)
    .bind(&request.source_revision_key)
    .bind(&request.sha256)
    .bind(request.byte_size)
    .bind(&request.storage_uri)
    .fetch_one(&mut **transaction)
    .await?;
    Ok(IngestOutcome {
        blob_id: row.try_get("blob_id")?,
        occurrence_id: row.try_get("occurrence_id")?,
        version_id: row.try_get("version_id")?,
        parent_version_id: row.try_get("parent_version_id")?,
        blob_created: row.try_get("blob_created")?,
        occurrence_created: row.try_get("occurrence_created")?,
        version_created: row.try_get("version_created")?,
    })
}

async fn concurrent_ingest(pool: &Pool<Postgres>, request: IngestObservation) -> IngestOutcome {
    let mut transaction = pool.begin().await.expect("begin concurrent intake");
    set_runtime_scope(&mut transaction, request.project_id).await;
    let outcome = invoke_atomic(&mut transaction, &request)
        .await
        .expect("concurrent atomic intake");
    transaction
        .commit()
        .await
        .expect("commit concurrent intake");
    outcome
}

#[tokio::test]
#[ignore = "requires explicit disposable PostgreSQL with migrations 001+002+003"]
async fn atomic_tenant_boundary_acceptance() {
    let confirmation = std::env::var("KF_TEST_DATABASE_CONFIRMATION")
        .expect("KF_TEST_DATABASE_CONFIRMATION is required for ignored database acceptance");
    assert_eq!(
        confirmation, CONFIRMATION,
        "refusing database acceptance without the exact destructive-test confirmation"
    );
    let cluster_confirmation = std::env::var("KF_TEST_CLUSTER_CONFIRMATION")
        .expect("KF_TEST_CLUSTER_CONFIRMATION is required for ignored database acceptance");
    assert_eq!(
        cluster_confirmation, CLUSTER_CONFIRMATION,
        "refusing database acceptance without the exact disposable-cluster confirmation"
    );
    let url = std::env::var("KF_TEST_DATABASE_URL")
        .expect("KF_TEST_DATABASE_URL must name a dedicated disposable test database");
    let store = PostgresMetaStore::connect_for_disposable_admin_test(
        &url,
        &confirmation,
        &cluster_confirmation,
    )
    .await
    .expect("validate and connect disposable test store");
    let expected_database = sqlx_core::Url::parse(&url)
        .expect("parse previously validated database URL")
        .path()
        .trim_start_matches('/')
        .to_owned();
    let expected_database_for_connections = expected_database.clone();
    let admin_pool = PoolOptions::<Postgres>::new()
        .max_connections(4)
        .after_connect(move |connection, _metadata| {
            let expected_database = expected_database_for_connections.clone();
            Box::pin(async move {
                verify_disposable_admin_connection(connection, &expected_database).await
            })
        })
        .connect(&url)
        .await
        .expect("connect guarded admin test pool");

    let project_a = Uuid::now_v7();
    let project_b = Uuid::now_v7();
    query("INSERT INTO public.project(project_id, slug) VALUES($1,$2),($3,$4)")
        .bind(project_a)
        .bind(format!(
            "atomic-a-{}",
            &project_a.simple().to_string()[..12]
        ))
        .bind(project_b)
        .bind(format!(
            "atomic-b-{}",
            &project_b.simple().to_string()[..12]
        ))
        .execute(&admin_pool)
        .await
        .expect("seed isolated projects");

    let shared_hash = unique_hash();
    let shared_uri = format!("cas://sha256/{shared_hash}");
    let first_request = input(
        project_a,
        "source-a",
        "revision-1",
        &shared_hash,
        &shared_uri,
    );
    let first = store
        .ingest_observation(&first_request)
        .await
        .expect("first atomic intake");
    assert!(first.blob_created && first.occurrence_created && first.version_created);
    assert!(first.parent_version_id.is_none());

    // Runtime can reach identity writes only through the definer function. Prove all three direct
    // INSERT paths fail with insufficient_privilege rather than merely trusting migration text.
    let denied_hash = unique_hash();
    let mut denied_blob = admin_pool.begin().await.expect("begin denied blob insert");
    set_runtime_scope(&mut denied_blob, project_a).await;
    let error = query(
        "INSERT INTO public.raw_blob(blob_id,sha256,byte_size,storage_uri) VALUES($1,$2,27,$3)",
    )
    .bind(Uuid::now_v7())
    .bind(&denied_hash)
    .bind(format!("cas://sha256/{denied_hash}"))
    .execute(&mut *denied_blob)
    .await
    .expect_err("runtime direct RawBlob INSERT must be denied");
    assert_permission_denied(error);
    denied_blob
        .rollback()
        .await
        .expect("rollback denied blob insert");

    let mut denied_occurrence = admin_pool
        .begin()
        .await
        .expect("begin denied occurrence insert");
    set_runtime_scope(&mut denied_occurrence, project_a).await;
    let error = query(
        "INSERT INTO public.artifact_occurrence(
             occurrence_id,project_id,source_system_id,source_native_id,blob_id
         ) VALUES($1,$2,'acceptance','direct-denied',$3)",
    )
    .bind(Uuid::now_v7())
    .bind(project_a)
    .bind(first.blob_id)
    .execute(&mut *denied_occurrence)
    .await
    .expect_err("runtime direct ArtifactOccurrence INSERT must be denied");
    assert_permission_denied(error);
    denied_occurrence
        .rollback()
        .await
        .expect("rollback denied occurrence insert");

    let mut denied_version = admin_pool
        .begin()
        .await
        .expect("begin denied version insert");
    set_runtime_scope(&mut denied_version, project_a).await;
    let error = query(
        "INSERT INTO public.artifact_version(
             version_id,occurrence_id,blob_id,source_revision_key,parent_version_id
         ) VALUES($1,$2,$3,'direct-denied',$4)",
    )
    .bind(Uuid::now_v7())
    .bind(first.occurrence_id)
    .bind(first.blob_id)
    .bind(first.version_id)
    .execute(&mut *denied_version)
    .await
    .expect_err("runtime direct ArtifactVersion INSERT must be denied");
    assert_permission_denied(error);
    denied_version
        .rollback()
        .await
        .expect("rollback denied version insert");

    // Migration re-application must repair every mutation ACL, not only INSERT on the three
    // identity tables. This also catches grant drift inherited through PUBLIC.
    let mutation_grants = query(
        "SELECT guarded.table_name, guarded.privilege
           FROM (VALUES
                 ('raw_blob'), ('artifact_occurrence'), ('artifact_version'),
                 ('logical_document'), ('ingestion_run'), ('event_ledger'),
                 ('project'), ('embedding_profile'), ('provenance_parent')
                ) AS guarded(table_name)
          CROSS JOIN (VALUES
                 ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
                ) AS mutation(privilege)
          WHERE pg_catalog.has_table_privilege(
                    'kf_runtime', 'public.' || guarded.table_name, mutation.privilege
                )",
    )
    .fetch_all(&admin_pool)
    .await
    .expect("inspect exact runtime mutation ACLs");
    assert!(
        mutation_grants.is_empty(),
        "kf_runtime retained forbidden mutation privileges"
    );
    let mutation_column_grants = query(
        "SELECT relation.relname, attribute.attname, mutation.privilege
           FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace
             ON namespace.oid = relation.relnamespace
           JOIN pg_catalog.pg_attribute AS attribute
             ON attribute.attrelid = relation.oid
          CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('REFERENCES')) AS mutation(privilege)
          WHERE namespace.nspname = 'public'
            AND relation.relkind IN ('r', 'p')
            AND attribute.attnum > 0
            AND NOT attribute.attisdropped
            AND pg_catalog.has_column_privilege(
                    'kf_runtime', relation.oid, attribute.attname, mutation.privilege
                )",
    )
    .fetch_all(&admin_pool)
    .await
    .expect("inspect runtime column mutation ACLs");
    assert!(
        mutation_column_grants.is_empty(),
        "kf_runtime retained forbidden column mutation privileges"
    );
    let drift = query(
        "SELECT pg_catalog.has_schema_privilege('kf_runtime', 'public', 'CREATE')
                    AS can_create_schema_objects,
                pg_catalog.has_database_privilege(
                    'kf_runtime', pg_catalog.current_database(), 'CREATE'
                ) AS can_create_database_objects,
                EXISTS (
                    SELECT 1
                      FROM pg_catalog.pg_database AS database
                      JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = database.datdba
                     WHERE database.datname = pg_catalog.current_database()
                       AND owner_role.rolname = 'kf_runtime'
                ) AS owns_database,
                EXISTS (
                    SELECT 1
                      FROM pg_catalog.pg_namespace AS namespace
                      JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
                     WHERE namespace.nspname = 'public'
                       AND owner_role.rolname = 'kf_runtime'
                ) AS owns_schema,
                EXISTS (
                    SELECT 1
                      FROM pg_catalog.pg_class AS relation
                      JOIN pg_catalog.pg_namespace AS namespace
                        ON namespace.oid = relation.relnamespace
                      JOIN pg_catalog.pg_roles AS owner_role
                        ON owner_role.oid = relation.relowner
                     WHERE namespace.nspname = 'public'
                       AND owner_role.rolname = 'kf_runtime'
                ) AS owns_relation",
    )
    .fetch_one(&admin_pool)
    .await
    .expect("inspect runtime schema and ownership drift");
    assert!(!drift
        .try_get::<bool, _>("can_create_schema_objects")
        .expect("can_create_schema_objects"));
    assert!(!drift
        .try_get::<bool, _>("can_create_database_objects")
        .expect("can_create_database_objects"));
    assert!(!drift
        .try_get::<bool, _>("owns_database")
        .expect("owns_database"));
    assert!(!drift
        .try_get::<bool, _>("owns_schema")
        .expect("owns_schema"));
    assert!(!drift
        .try_get::<bool, _>("owns_relation")
        .expect("owns_relation"));
    let rls_drift = query(
        "SELECT expected.table_name
           FROM (VALUES
                ('artifact_occurrence'), ('artifact_version'), ('logical_document'),
                ('ingestion_run'), ('event_ledger'), ('raw_blob'), ('project')
           ) AS expected(table_name)
          WHERE NOT EXISTS (
              SELECT 1
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
               WHERE namespace.nspname = 'public'
                 AND relation.relname = expected.table_name
                 AND relation.relkind IN ('r', 'p')
                 AND relation.relrowsecurity
                 AND relation.relforcerowsecurity
          )",
    )
    .fetch_all(&admin_pool)
    .await
    .expect("inspect exact scoped-table RLS flags");
    assert!(rls_drift.is_empty(), "scoped table RLS flags drifted");

    let idempotent_request = input(
        project_a,
        "source-a",
        "revision-1",
        &shared_hash,
        &shared_uri,
    );
    let idempotent = store
        .ingest_observation(&idempotent_request)
        .await
        .expect("idempotent atomic intake");
    assert!(
        !idempotent.blob_created && !idempotent.occurrence_created && !idempotent.version_created
    );
    assert_eq!(idempotent.blob_id, first.blob_id);
    assert_eq!(idempotent.occurrence_id, first.occurrence_id);
    assert_eq!(idempotent.version_id, first.version_id);
    assert_eq!(idempotent.parent_version_id, first.parent_version_id);

    let second_source = input(
        project_a,
        "source-b",
        "revision-1",
        &shared_hash,
        &shared_uri,
    );
    let second = store
        .ingest_observation(&second_source)
        .await
        .expect("deduplicated second source");
    assert!(!second.blob_created && second.occurrence_created && second.version_created);
    assert!(second.parent_version_id.is_none());
    assert_eq!(second.blob_id, first.blob_id);
    assert_eq!(
        store
            .occurrences_for_blob(project_a, first.blob_id)
            .await
            .expect("count scoped occurrences"),
        2
    );

    let mut metadata_conflict = input(
        project_a,
        "source-c",
        "revision-1",
        &shared_hash,
        "cas://wrong",
    );
    metadata_conflict.byte_size = 28;
    assert!(
        store.ingest_observation(&metadata_conflict).await.is_err(),
        "same hash with different immutable metadata must fail"
    );

    // The stable source identity accepts a new blob only as a new version whose parent is the
    // latest durable version.
    let revision_two_hash = unique_hash();
    let revision_two_uri = format!("cas://sha256/{revision_two_hash}");
    let revision_two = input(
        project_a,
        "source-a",
        "revision-2",
        &revision_two_hash,
        &revision_two_uri,
    );
    let revision_two_outcome = store
        .ingest_observation(&revision_two)
        .await
        .expect("append second source revision");
    assert!(revision_two_outcome.blob_created);
    assert!(!revision_two_outcome.occurrence_created);
    assert!(revision_two_outcome.version_created);
    assert_eq!(revision_two_outcome.occurrence_id, first.occurrence_id);
    assert_eq!(
        revision_two_outcome.parent_version_id,
        Some(first.version_id)
    );
    assert!(
        store
            .blob_by_hash(project_a, &shared_hash)
            .await
            .expect("read first-version blob")
            .is_some(),
        "initial occurrence blob must remain visible"
    );
    assert!(
        store
            .blob_by_hash(project_a, &revision_two_hash)
            .await
            .expect("read later-version blob")
            .is_some(),
        "later version blob must be visible through version lineage"
    );
    assert!(
        store
            .blob_by_hash(project_b, &shared_hash)
            .await
            .expect("cross-project initial blob query")
            .is_none(),
        "other project must not see initial blob"
    );
    assert!(
        store
            .blob_by_hash(project_b, &revision_two_hash)
            .await
            .expect("cross-project version blob query")
            .is_none(),
        "other project must not see later-version blob"
    );

    // Reusing revision-2 for other content occurs after a new RawBlob insert inside the definer.
    // The revision conflict must roll the entire transaction back, including that blob.
    let rollback_hash = unique_hash();
    let rollback_uri = format!("cas://sha256/{rollback_hash}");
    let revision_conflict = input(
        project_a,
        "source-a",
        "revision-2",
        &rollback_hash,
        &rollback_uri,
    );
    assert!(
        store.ingest_observation(&revision_conflict).await.is_err(),
        "one source revision cannot silently move to another blob"
    );
    let rollback_row = query("SELECT count(*) AS n FROM public.raw_blob WHERE sha256=$1")
        .bind(&rollback_hash)
        .fetch_one(&admin_pool)
        .await
        .expect("verify failed intake rollback");
    assert_eq!(rollback_row.try_get::<i64, _>("n").expect("count"), 0);

    // Explicit A scope cannot call the privileged function for B.
    let cross_hash = unique_hash();
    let cross_uri = format!("cas://sha256/{cross_hash}");
    let cross_request = input(
        project_b,
        "cross-project",
        "revision-1",
        &cross_hash,
        &cross_uri,
    );
    let mut cross_transaction = admin_pool.begin().await.expect("begin cross-scope test");
    set_runtime_scope(&mut cross_transaction, project_a).await;
    assert!(
        invoke_atomic(&mut cross_transaction, &cross_request)
            .await
            .is_err(),
        "A scope must not write B identity"
    );
    cross_transaction
        .rollback()
        .await
        .expect("rollback denied cross-scope write");

    // B scope cannot read A occurrence through RLS.
    let mut read_transaction = admin_pool.begin().await.expect("begin cross-read test");
    set_runtime_scope(&mut read_transaction, project_b).await;
    let hidden =
        query("SELECT occurrence_id FROM public.artifact_occurrence WHERE occurrence_id=$1")
            .bind(first.occurrence_id)
            .fetch_optional(&mut *read_transaction)
            .await
            .expect("query cross-project occurrence");
    assert!(hidden.is_none(), "B scope must not observe A occurrence");
    read_transaction
        .rollback()
        .await
        .expect("finish cross-read test");

    // Transaction-local scope must disappear before the same one-connection pool is reused.
    let reuse_pool = PoolOptions::<Postgres>::new()
        .max_connections(1)
        .connect(&url)
        .await
        .expect("connect reuse test pool");
    let mut scoped = reuse_pool
        .begin()
        .await
        .expect("begin scoped reuse transaction");
    set_runtime_scope(&mut scoped, project_a).await;
    scoped
        .commit()
        .await
        .expect("commit scoped reuse transaction");
    let mut reused = reuse_pool.begin().await.expect("reuse pooled connection");
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut *reused)
        .await
        .expect("restore runtime role without project context");
    let context_row =
        query("SELECT pg_catalog.current_setting('app.project_ids', true) AS project_context")
            .fetch_one(&mut *reused)
            .await
            .expect("read reused connection context");
    let leaked: Option<String> = context_row
        .try_get("project_context")
        .expect("decode context");
    assert!(
        leaked.as_deref().unwrap_or_default().is_empty(),
        "transaction-local project context leaked through pool reuse"
    );
    reused.rollback().await.expect("finish reuse test");

    // Two concurrent sources with identical bytes converge on one RawBlob.
    let concurrent_hash = unique_hash();
    let concurrent_uri = format!("cas://sha256/{concurrent_hash}");
    let concurrent_a = input(
        project_a,
        "concurrent-a",
        "revision-1",
        &concurrent_hash,
        &concurrent_uri,
    );
    let concurrent_b = input(
        project_a,
        "concurrent-b",
        "revision-1",
        &concurrent_hash,
        &concurrent_uri,
    );
    let (outcome_a, outcome_b) = tokio::join!(
        concurrent_ingest(&admin_pool, concurrent_a),
        concurrent_ingest(&admin_pool, concurrent_b)
    );
    assert_eq!(outcome_a.blob_id, outcome_b.blob_id);
    assert_ne!(outcome_a.blob_created, outcome_b.blob_created);
    assert!(outcome_a.occurrence_created && outcome_b.occurrence_created);
    assert!(outcome_a.version_created && outcome_b.version_created);
    assert_eq!(
        store
            .occurrences_for_blob(project_a, outcome_a.blob_id)
            .await
            .expect("count concurrent occurrences"),
        2
    );

    // Concurrent revisions of one occurrence form a chain, never two siblings of the same
    // latest parent. Acquisition order is intentionally unspecified, but the graph is linear.
    let lineage_base_hash = unique_hash();
    let lineage_base_uri = format!("cas://sha256/{lineage_base_hash}");
    let lineage_base = store
        .ingest_observation(&input(
            project_a,
            "lineage-concurrent",
            "revision-0",
            &lineage_base_hash,
            &lineage_base_uri,
        ))
        .await
        .expect("seed concurrent lineage");
    let lineage_hash_a = unique_hash();
    let lineage_hash_b = unique_hash();
    let lineage_uri_a = format!("cas://sha256/{lineage_hash_a}");
    let lineage_uri_b = format!("cas://sha256/{lineage_hash_b}");
    let lineage_a = input(
        project_a,
        "lineage-concurrent",
        "revision-a",
        &lineage_hash_a,
        &lineage_uri_a,
    );
    let lineage_b = input(
        project_a,
        "lineage-concurrent",
        "revision-b",
        &lineage_hash_b,
        &lineage_uri_b,
    );
    let (lineage_outcome_a, lineage_outcome_b) = tokio::join!(
        concurrent_ingest(&admin_pool, lineage_a),
        concurrent_ingest(&admin_pool, lineage_b)
    );
    let a_then_b = lineage_outcome_a.parent_version_id == Some(lineage_base.version_id)
        && lineage_outcome_b.parent_version_id == Some(lineage_outcome_a.version_id);
    let b_then_a = lineage_outcome_b.parent_version_id == Some(lineage_base.version_id)
        && lineage_outcome_a.parent_version_id == Some(lineage_outcome_b.version_id);
    assert!(
        a_then_b || b_then_a,
        "concurrent version lineage must be linear"
    );
    let terminal_version_id = if a_then_b {
        lineage_outcome_b.version_id
    } else {
        lineage_outcome_a.version_id
    };
    let post_concurrency_hash = unique_hash();
    let post_concurrency_uri = format!("cas://sha256/{post_concurrency_hash}");
    let post_concurrency = store
        .ingest_observation(&input(
            project_a,
            "lineage-concurrent",
            "revision-after-concurrency",
            &post_concurrency_hash,
            &post_concurrency_uri,
        ))
        .await
        .expect("append after concurrent lineage");
    assert_eq!(
        post_concurrency.parent_version_id,
        Some(terminal_version_id),
        "post-concurrency revision must extend the graph tail"
    );
}
