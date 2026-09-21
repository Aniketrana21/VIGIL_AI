import sys
import asyncio
from app.db.connection import get_db_pool

async def main():
    if len(sys.argv) < 2:
        print("Usage: python block_number.py <phone_number_to_block>")
        return

    phone = sys.argv[1].strip()
    pool = await get_db_pool()
    if not pool:
        print("No DB pool")
        return

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id FROM public.users LIMIT 1;")
        user_id = user["id"]

        # Check existing
        existing = await conn.fetchrow(
            "SELECT caller_id FROM public.phone_numbers WHERE phone_number = $1 OR normalized_number = $1;",
            phone
        )
        if existing:
            await conn.execute(
                "UPDATE public.callers SET trust_status = 'blocked', display_name = $2 WHERE id = $1;",
                existing["caller_id"], f"Blocked Caller ({phone})"
            )
            print(f"Updated existing caller {phone} to trust_status='blocked'!")
        else:
            caller_id = await conn.fetchval(
                """
                INSERT INTO public.callers (user_id, display_name, trust_status, is_vip, caller_type)
                VALUES ($1, $2, 'blocked', false, 'unknown')
                RETURNING id;
                """,
                user_id, f"Blocked Caller ({phone})"
            )
            await conn.execute(
                """
                INSERT INTO public.phone_numbers (
                    caller_id, phone_number, country_code, normalized_number, is_primary, is_verified, line_type
                ) VALUES ($1, $2, '+91', $2, true, false, 'mobile')
                ON CONFLICT (caller_id, normalized_number) DO UPDATE SET is_primary = true;
                """,
                caller_id, phone
            )
            print(f"Enrolled new caller {phone} as BLOCKED with Caller ID: {caller_id}!")

if __name__ == "__main__":
    asyncio.run(main())
