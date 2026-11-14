# Database setup

`python -m scripts.migrate` prepares the configured database without dropping
data. It creates missing tables from the SQLAlchemy metadata and, on PostgreSQL
with `PGVECTOR_ENABLED=true`, runs:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

This is appropriate for a fresh deployment and local development. Before changing
an existing production schema, adopt a versioned migration tool (for example
Alembic) and review generated SQL. Never let an unreviewed migration drop ledger
or audit data.

## Production checklist

1. Use a PostgreSQL `DATABASE_URL` with `sslmode=require`.
2. Set a strong `JWT_SECRET`; `ENVIRONMENT=production` rejects SQLite and weak
   secrets.
3. Provision the pgvector extension before setting `PGVECTOR_ENABLED=true`.
4. Set `AUTO_CREATE_TABLES=false` once schema changes are applied deliberately.
5. Run `python -m scripts.migrate` and then `python -m scripts.create_admin`.
6. Keep `storage` on durable storage or use `STORAGE_BACKEND=supabase`.
