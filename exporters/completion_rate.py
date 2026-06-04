import csv
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class CompletionRateExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime = None, end_date: datetime = None, progress_callback=None, **kwargs) -> None:
        month_limit = 3
        week_limit = 3
        # Queries to fetch periods
        month_periods_query = text("""
            SELECT DISTINCT period_start, period_end 
            FROM partner_completion_metrics 
            WHERE period_type = 'month' AND period_start != period_end
            ORDER BY period_start DESC LIMIT :limit
        """)

        week_periods_query = text("""
            SELECT DISTINCT period_start, period_end 
            FROM partner_completion_metrics 
            WHERE period_type = 'week' AND period_start != period_end
            ORDER BY period_start DESC LIMIT :limit
        """)

        # Connect to database and retrieve periods
        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            
            month_result = await conn.execute(month_periods_query, {"limit": month_limit})
            months = sorted(month_result.fetchall(), key=lambda x: x.period_start)

            week_result = await conn.execute(week_periods_query, {"limit": week_limit})
            weeks = sorted(week_result.fetchall(), key=lambda x: x.period_start)

            # Assemble Headers
            headers = [
                'Partner ID',
                'Partner Name',
                'Partner Status',
                'Location',
                'District',
                'Code',
                'Growth Manager'
            ]

            # Dynamic header column names mapping
            for m in months:
                label = m.period_start.strftime("%b-%Y")
                headers.append(f"{label} %")
            for m in months:
                label = m.period_start.strftime("%b-%Y")
                headers.append(f"{label} Total")
            for w in weeks:
                label = f"{w.period_start.strftime('%d %b')}-{w.period_end.strftime('%d %b')}"
                headers.append(f"{label} %")
            for w in weeks:
                label = f"{w.period_start.strftime('%d %b')}-{w.period_end.strftime('%d %b')}"
                headers.append(f"{label} Total")
            for m in months:
                label = m.period_start.strftime("%b-%Y")
                headers.append(f"{label} Compld")
                headers.append(f"{label} Total Billing")
            for w in weeks:
                label = f"{w.period_start.strftime('%d %b')}-{w.period_end.strftime('%d %b')}"
                headers.append(f"{label} Compld")
                headers.append(f"{label} Total Billing")

            # Fetch all salons list
            salons_query = text("""
                SELECT id, salon_name, is_disabled, salon_location, district, partner_code 
                FROM salons
            """)
            salons_result = await conn.execute(salons_query)
            salons = salons_result.fetchall()

            # Create output writer targeting the stream directly
            writer = csv.writer(output_file)
            writer.writerow(headers)

            # Process every salon row
            processed_count = 0
            for s in salons:
                row = [
                    s.id,
                    s.salon_name,
                    'Disabled' if s.is_disabled else 'Enabled',
                    s.salon_location,
                    s.district,
                    s.partner_code,
                    'N/A' # growth manager placeholder
                ]

                # Append metrics placeholders matching dynamic column size
                for m in months:
                    row.append(0.0) # rate
                for m in months:
                    row.append(0) # total
                for w in weeks:
                    row.append(0.0) # rate
                for w in weeks:
                    row.append(0) # total
                for m in months:
                    row.append(0) # completed
                    row.append(0.0) # billing
                for w in weeks:
                    row.append(0) # completed
                    row.append(0.0) # billing

                writer.writerow(row)
                processed_count += 1
                if progress_callback and processed_count % 500 == 0:
                    await progress_callback(processed_count)
