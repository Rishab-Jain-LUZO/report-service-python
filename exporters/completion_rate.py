import csv
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class CompletionRateExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime = None, end_date: datetime = None, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {})
        month_limit = payload.get("monthLimit", 3)
        week_limit = payload.get("weekLimit", 3)
        if month_limit is None:
            month_limit = 3
        if week_limit is None:
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
            
            month_result = await conn.execute(month_periods_query, {"limit": int(month_limit)})
            months = sorted(month_result.fetchall(), key=lambda x: x.period_start)

            week_result = await conn.execute(week_periods_query, {"limit": int(week_limit)})
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
                WHERE deleted_at IS NULL
                ORDER BY id ASC
            """)
            salons_result = await conn.execute(salons_query)
            salons = salons_result.fetchall()

            # Pre-fetch RM names mapping
            rm_query = text("""
                SELECT rms.salon_id, u.name AS rm_name
                FROM rm_salon rms
                JOIN users u ON rms.rm_id = u.id
            """)
            rm_result = await conn.execute(rm_query)
            rm_map = {row.salon_id: row.rm_name for row in rm_result.fetchall()}

            # Pre-fetch metrics in bulk
            metrics_query = text("""
                SELECT salon_id, period_type, period_start, completion_rate, total_appointments, completed_appointments
                FROM partner_completion_metrics
            """)
            metrics_result = await conn.execute(metrics_query)
            metrics_map = {}
            for row in metrics_result.fetchall():
                key = (row.salon_id, row.period_type, str(row.period_start))
                metrics_map[key] = row

            # Load monthly billing sums for each period
            month_billings = {}
            for m in months:
                billing_query = text("""
                    SELECT salon_id, SUM(total_price) AS total
                    FROM salonsurf_pro_payments
                    WHERE created_at >= :start_date AND created_at <= :end_date
                    GROUP BY salon_id
                """)
                res = await conn.execute(billing_query, {
                    "start_date": m.period_start.strftime("%Y-%m-%d 00:00:00"), 
                    "end_date": m.period_end.strftime("%Y-%m-%d 23:59:59")
                })
                for r in res.fetchall():
                    month_billings[(r.salon_id, str(m.period_start))] = float(r.total or 0.0)

            # Load weekly billing sums for each period
            week_billings = {}
            for w in weeks:
                billing_query = text("""
                    SELECT salon_id, SUM(total_price) AS total
                    FROM salonsurf_pro_payments
                    WHERE created_at >= :start_date AND created_at <= :end_date
                    GROUP BY salon_id
                """)
                res = await conn.execute(billing_query, {
                    "start_date": w.period_start.strftime("%Y-%m-%d 00:00:00"), 
                    "end_date": w.period_end.strftime("%Y-%m-%d 23:59:59")
                })
                for r in res.fetchall():
                    week_billings[(r.salon_id, str(w.period_start))] = float(r.total or 0.0)

            # Create output writer targeting the stream directly
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            # Process every salon row
            processed_count = 0
            for s in salons:
                rm_name = rm_map.get(s.id, "N/A")
                row = [
                    s.id,
                    s.salon_name,
                    'Disabled' if s.is_disabled else 'Enabled',
                    s.salon_location,
                    s.district,
                    s.partner_code,
                    rm_name
                ]

                # Month Completion %
                for m in months:
                    key = (s.id, 'month', str(m.period_start))
                    metric = metrics_map.get(key)
                    if metric is None or getattr(metric, "total_appointments", 0) == 0:
                        row.append("")
                    else:
                        row.append(round(float(getattr(metric, "completion_rate", 0.0)), 2))

                # Month Totals
                for m in months:
                    key = (s.id, 'month', str(m.period_start))
                    metric = metrics_map.get(key)
                    row.append(int(getattr(metric, "total_appointments", 0) or 0))

                # Week Completion %
                for w in weeks:
                    key = (s.id, 'week', str(w.period_start))
                    metric = metrics_map.get(key)
                    if metric is None or getattr(metric, "total_appointments", 0) == 0:
                        row.append("")
                    else:
                        row.append(round(float(getattr(metric, "completion_rate", 0.0)), 2))

                # Week Totals
                for w in weeks:
                    key = (s.id, 'week', str(w.period_start))
                    metric = metrics_map.get(key)
                    row.append(int(getattr(metric, "total_appointments", 0) or 0))

                # Month Completed & Month Billing
                for m in months:
                    key = (s.id, 'month', str(m.period_start))
                    metric = metrics_map.get(key)
                    row.append(int(getattr(metric, "completed_appointments", 0) or 0))
                    mbill = month_billings.get((s.id, str(m.period_start)), 0.0)
                    row.append(f"{mbill:.2f}")

                # Week Completed & Week Billing
                for w in weeks:
                    key = (s.id, 'week', str(w.period_start))
                    metric = metrics_map.get(key)
                    row.append(int(getattr(metric, "completed_appointments", 0) or 0))
                    wbill = week_billings.get((s.id, str(w.period_start)), 0.0)
                    row.append(f"{wbill:.2f}")

                writer.writerow(row)
                processed_count += 1
                if progress_callback and processed_count % 500 == 0:
                    await progress_callback(processed_count)
