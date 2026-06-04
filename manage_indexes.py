import asyncio
from sqlalchemy import text
from db import AsyncSessionLocal, engine

async def manage_indexes():
    # List of indexes to ensure
    # format: (table, index_name, columns)
    indexes_to_check = [
        ("salon_appointment", "idx_salon_appointment_salon_id", "salon_id"),
        ("salon_appointment", "idx_salon_appointment_customer_id", "customer_id"),
        ("salon_appointment", "idx_salon_appointment_created_at", "created_at"),
        ("salon_appointment", "idx_salon_appointment_appointment_date", "appointment_date"),
        ("cancellation_reasons", "idx_cancellation_reasons_appointment_id", "appointment_id"),
        ("salons", "idx_salons_deleted_at", "deleted_at")
    ]
    
    async with AsyncSessionLocal() as session:
        conn = await session.connection()
        for table, index_name, columns in indexes_to_check:
            # Query existing indexes for the table
            query = text(f"SHOW INDEX FROM {table} WHERE Key_name = :index_name")
            result = await conn.execute(query, {"index_name": index_name})
            exists = result.fetchone()
            
            if exists:
                print(f"Index '{index_name}' already exists on table '{table}'.")
            else:
                print(f"Index '{index_name}' does not exist on table '{table}'. Creating it now...")
                try:
                    create_query = text(f"ALTER TABLE {table} ADD INDEX {index_name} ({columns})")
                    await conn.execute(create_query)
                    # Commit the DDL operation (though DDL in MySQL causes implicit commit)
                    await conn.commit()
                    print(f"Successfully created index '{index_name}'.")
                except Exception as e:
                    print(f"Failed to create index '{index_name}': {str(e)}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(manage_indexes())
