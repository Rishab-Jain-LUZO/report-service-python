import asyncio
import time
from sqlalchemy import text
from db import AsyncSessionLocal

async def main():
    query = """
        SELECT shp.salon_head_wallet_id, shp.margin_received
        FROM salon_head_passbooks shp
        INNER JOIN (
            SELECT salon_head_wallet_id, MAX(id) as max_id
            FROM salon_head_passbooks
            WHERE transaction_type = 1 AND deleted_at IS NULL
            GROUP BY salon_head_wallet_id
        ) latest ON shp.id = latest.max_id
    """
    async with AsyncSessionLocal() as session:
        t0 = time.time()
        result = await session.execute(text(query))
        rows = result.all()
        elapsed = time.time() - t0
        print(f"Query returned {len(rows)} rows in {elapsed:.4f} seconds.")
        # print first few results
        print(rows[:5])

if __name__ == "__main__":
    asyncio.run(main())
