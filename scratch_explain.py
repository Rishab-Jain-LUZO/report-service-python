import asyncio
from sqlalchemy import text
from db import AsyncSessionLocal

async def main():
    query = """
        EXPLAIN SELECT shp.salon_head_wallet_id, shp.margin_received
        FROM salon_head_passbooks shp
        INNER JOIN (
            SELECT salon_head_wallet_id, MAX(id) as max_id
            FROM salon_head_passbooks
            WHERE transaction_type = 1 AND deleted_at IS NULL
            GROUP BY salon_head_wallet_id
        ) latest ON shp.id = latest.max_id
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(query))
        rows = result.all()
        print(f"{'id':<3} | {'select_type':<15} | {'table':<10} | {'type':<6} | {'possible_keys':<20} | {'key':<15} | {'rows':<10} | {'Extra'}")
        print("-" * 110)
        for r in rows:
            print(f"{r[0]:<3} | {r[1]:<15} | {str(r[2]):<10} | {str(r[3]):<6} | {str(r[4]):<20} | {str(r[5]):<15} | {str(r[8]):<10} | {str(r[9])}")

if __name__ == "__main__":
    asyncio.run(main())
