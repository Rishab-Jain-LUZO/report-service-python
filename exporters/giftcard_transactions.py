import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class GiftCardTransactionExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {}) or {}
        
        start_date_str = payload.get("startDate") or payload.get("start_date")
        end_date_str = payload.get("endDate") or payload.get("end_date")
        status = payload.get("status")
        search_term = payload.get("searchTerm") or payload.get("search_term")
        
        where_clauses = []
        params = {}
        
        if start_date_str:
            where_clauses.append("gt.created_at >= :start_date")
            params["start_date"] = f"{start_date_str} 00:00:00"
        if end_date_str:
            where_clauses.append("gt.created_at <= :end_date")
            params["end_date"] = f"{end_date_str} 23:59:59"
            
        if status:
            if status == "CLAIMED":
                where_clauses.append("gt.claimed_at IS NOT NULL")
            elif status == "UNCLAIMED":
                where_clauses.append("gt.claimed_at IS NULL")
                
        if search_term:
            where_clauses.append("""
                (
                    purchasing_customer.name LIKE :search
                    OR purchasing_customer.contact LIKE :search
                    OR claiming_customer.name LIKE :search
                    OR claiming_customer.contact LIKE :search
                )
            """)
            params["search"] = f"%{search_term}%"
            
        where_clause_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        query = text(f"""
            SELECT 
                purchasing_customer.name AS purchasing_customer, 
                purchasing_customer.contact AS purchasing_customer_contact,
                purchasing_customer.gender AS purchasing_customer_gender, 
                gt.amount, 
                claiming_customer.name AS claiming_customer_name,
                claiming_customer.contact AS claiming_customer_contact, 
                gt.created_at AS purchased_at,
                IF(gt.claimed_at IS NULL, 'UNCLAIMED', 'CLAIMED') AS status, 
                gt.claimed_at
            FROM giftcard_transactions gt
            LEFT JOIN customers AS purchasing_customer ON purchasing_customer.id = gt.customer_id
            LEFT JOIN customers AS claiming_customer ON claiming_customer.id = gt.claimed_by_user_id
            WHERE {where_clause_str}
            ORDER BY gt.id DESC
        """)
        
        headers = [
            "Purchasing Customer", "Purchasing Customer Contact", "Gender", "Amount", "Claiming Customer", "Claiming Customer Contact",
            "Purchased At", "Status", "Claimed At"
        ]
        
        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            result_stream = await conn.stream(query, params)
            
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)
            
            gc.disable()
            try:
                processed_count = 0
                async for partition in result_stream.partitions(1000):
                    rows_to_write = []
                    for row in partition:
                        purchased_at = row.purchased_at.strftime("%Y-%m-%d %H:%M:%S") if row.purchased_at else ""
                        claimed_at = row.claimed_at.strftime("%Y-%m-%d %H:%M:%S") if row.claimed_at else ""
                        
                        gender = row.purchasing_customer_gender
                        if gender:
                            gender = gender.lower()
                            
                        amount = float(row.amount) if row.amount is not None else 0.0
                        
                        rows_to_write.append([
                            row.purchasing_customer or "",
                            row.purchasing_customer_contact or "",
                            gender or "",
                            amount,
                            row.claiming_customer_name or "",
                            row.claiming_customer_contact or "",
                            purchased_at,
                            row.status or "UNCLAIMED",
                            claimed_at
                        ])
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
