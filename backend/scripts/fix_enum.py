import asyncio
from app.db.connection import get_db_pool

async def main():
    pool = await get_db_pool()
    if not pool:
        print("No pool")
        return
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TYPE call_action_enum ADD VALUE IF NOT EXISTS 'MONITOR';")
            print("Successfully added MONITOR to call_action_enum in Supabase PostgreSQL!")
        except Exception as e:
            print("Enum alter:", e)

if __name__ == "__main__":
    asyncio.run(main())
