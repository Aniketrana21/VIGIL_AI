"""
VIGIL-AI: Automated Supabase PostgreSQL Production Migration Runner.
Connects directly to Supabase PostgreSQL (via Session Pooler port 5432)
and executes the complete normalized production database schema.
"""
import asyncio
import os
import sys
from pathlib import Path
import asyncpg

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Supabase Production Connection Specs
HOST = "aws-0-ap-northeast-1.pooler.supabase.com"
PORT = 6543
USER = "postgres.rxtisiznzwzkwzmfgojf"
PASSWORD = "VIGIL_AI@06$"
DATABASE = "postgres"


async def apply_migration():
    schema_path = Path(__file__).resolve().parent.parent / "docs" / "supabase_schema.sql"
    if not schema_path.exists():
        print(f"❌ Schema file not found at: {schema_path}")
        return False

    with open(schema_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print("=" * 80)
    print("🚀 VIGIL-AI: AUTOMATED SUPABASE PRODUCTION MIGRATION")
    print("=" * 80)
    print(f"• Host     : {HOST}:{PORT}")
    print(f"• User     : {USER}")
    print(f"• Database : {DATABASE}")
    print(f"• Script   : {schema_path}")
    print("-" * 80)

    try:
        print("Connecting to Supabase PostgreSQL...")
        conn = await asyncpg.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            database=DATABASE,
            timeout=15.0,
            statement_cache_size=0
        )
        print(" Connected successfully to Supabase PostgreSQL!")

        print("\nExecuting production DDL schema migration...")
        # Execute migration SQL script
        await conn.execute(sql_content)
        print(" Schema migration executed successfully!")

        # Verify created tables
        print("\nVerifying created tables in 'public' schema...")
        rows = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        created_tables = [r["table_name"] for r in rows]
        print(f"Found {len(created_tables)} tables:")
        for t in created_tables:
            print(f"  • {t}")

        # Verify pgvector extension
        print("\nVerifying extensions...")
        exts = await conn.fetch("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
        if exts:
            print(f"  • pgvector active: version {exts[0]['extversion']}")
        else:
            print("  ⚠️ pgvector extension not found!")

        # Verify RLS enabled on tables
        print("\nVerifying Row Level Security (RLS)...")
        rls_rows = await conn.fetch("""
            SELECT relname, relrowsecurity 
            FROM pg_class 
            JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
            WHERE pg_namespace.nspname = 'public' AND relkind = 'r'
            ORDER BY relname;
        """)
        for r in rls_rows:
            status = "ENABLED" if r["relrowsecurity"] else "DISABLED"
            print(f"  • {r['relname']:<28}: RLS {status}")

        # Verify Realtime publications
        print("\nVerifying Supabase Realtime publication...")
        pub_rows = await conn.fetch("""
            SELECT tablename 
            FROM pg_publication_tables 
            WHERE pubname = 'supabase_realtime' AND schemaname = 'public'
            ORDER BY tablename;
        """)
        print(f"Realtime tables ({len(pub_rows)}): {[r['tablename'] for r in pub_rows]}")

        await conn.close()
        print("\n" + "=" * 80)
        print("🎉 PRODUCTION SUPABASE DATABASE FULLY PROVISIONED AND READY!")
        print("=" * 80)
        return True
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(apply_migration())
