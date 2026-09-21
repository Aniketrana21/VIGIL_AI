import asyncio
from app.db.connection import get_db_pool

import sys

async def main():
    pool = await get_db_pool()
    if not pool:
        print("Failed to initialize database pool.")
        return

    if len(sys.argv) < 2:
        print("Usage: python enroll_subscriber.py <phone_number> [display_name] [user_id]")
        return

    phone = sys.argv[1]
    subscriber_name = sys.argv[2] if len(sys.argv) > 2 else f"Caller ({phone})"
    custom_user_id = sys.argv[3] if len(sys.argv) > 3 else None

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, name, email FROM public.users LIMIT 1;")
        user_id = custom_user_id or (user["id"] if user else None)
        print(f"Using User ID: {user_id}")

        # Check existing phone number
        existing = await conn.fetchrow(
            "SELECT caller_id FROM public.phone_numbers WHERE phone_number = $1;",
            phone
        )
        if existing:
            caller = await conn.fetchrow(
                "SELECT id, display_name FROM public.callers WHERE id = $1;",
                existing["caller_id"]
            )
            print(f"Subscriber {phone} is already enrolled as: {caller['display_name']} (ID: {caller['id']})")
            return

        caller_id = await conn.fetchval(
            """
            INSERT INTO public.callers (user_id, display_name, trust_status, is_vip, caller_type)
            VALUES ($1, $2, 'trusted', true, 'individual')
            RETURNING id;
            """,
            user_id, subscriber_name
        )

        await conn.execute(
            """
            INSERT INTO public.phone_numbers (
                caller_id, phone_number, country_code, normalized_number, is_primary, is_verified, line_type
            )
            VALUES ($1, $2, '+91', $2, true, true, 'mobile')
            ON CONFLICT (caller_id, normalized_number) DO NOTHING;
            """,
            caller_id, phone
        )

        print(f"SUCCESS: Enrolled {subscriber_name} with phone {phone} into Supabase (Caller ID: {caller_id})")

if __name__ == "__main__":
    asyncio.run(main())
