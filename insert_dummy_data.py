import asyncio
import random
import time
from datetime import datetime, timedelta
from sqlalchemy import text
from db import AsyncSessionLocal

async def main():
    customer_ids = [1, 515, 518, 519, 523]
    salon_ids = [14, 16, 17, 18, 22]
    salon_head_ids = [1, 2, 3, 4, 5]
    salon_head_wallet_ids = [1, 2, 3, 4, 5]
    scheme_types = ['A', 'B', 'C']
    transaction_types = [1, 2, 3, 4, 5, 6, 7]
    
    total_rows = 3000000
    batch_size = 10000
    
    start_date = datetime(2025, 6, 4)
    
    print(f"Starting insertion of {total_rows:,} dummy rows...")
    
    async with AsyncSessionLocal() as session:
        conn = await session.connection()
        await conn.execute(text("SET UNIQUE_CHECKS=0"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        
        row_count = 0
        t_start = time.time()
        
        while row_count < total_rows:
            values = []
            for _ in range(batch_size):
                sh_id = random.choice(salon_head_ids)
                shw_id = random.choice(salon_head_wallet_ids)
                s_id = random.choice(salon_ids)
                c_id = random.choice(customer_ids)
                scheme = random.choice(scheme_types)
                txn_type = random.choice(transaction_types)
                amount = round(random.uniform(500, 5000), 2)
                final_amount = round(amount * random.uniform(0.8, 1.0), 2)
                
                # Distribute dates across last year
                days_offset = random.randint(0, 365)
                txn_date = (start_date + timedelta(days=days_offset)).strftime('%Y-%m-%d')
                
                values.append(f"({sh_id}, {shw_id}, {s_id}, {c_id}, '{scheme}', {txn_type}, {amount}, {final_amount}, '{txn_date}', 0.00, 0, 0, 0)")
            
            query = f"""
                INSERT INTO salon_head_passbooks 
                (salon_head_id, salon_head_wallet_id, salon_id, customer_id, scheme_type, transaction_type, amount, final_amount, txn_date, penalty_amt, is_refund_reversal, is_invoice_received, is_utilized) 
                VALUES {','.join(values)}
            """
            await conn.execute(text(query))
            row_count += batch_size
            
            if row_count % 100000 == 0:
                elapsed = time.time() - t_start
                rate = row_count / elapsed
                rem_rows = total_rows - row_count
                eta = rem_rows / rate if rate > 0 else 0
                print(f"Inserted {row_count:,} / {total_rows:,} rows... Speed: {rate:.1f} rows/sec, ETA: {eta:.1f}s")
                await session.commit()
                
                # Re-acquire connection and disable checks for the new transaction
                conn = await session.connection()
                await conn.execute(text("SET UNIQUE_CHECKS=0"))
                await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
                
        # Re-enable checks
        await conn.execute(text("SET UNIQUE_CHECKS=1"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        await session.commit()
        
    print("Dummy data generation completed successfully!")

if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(main())
    print(f"Total time taken: {time.time() - t0:.2f} seconds")
