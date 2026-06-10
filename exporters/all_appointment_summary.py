import csv
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class AppointmentSummaryExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        # Define the SQL query matching the Laravel Eloquent builder
        query = text("""
            WITH base_appointments AS (
                SELECT 
                    sa.id,
                    sa.is_served,
                    sa.is_cancelled,
                    sa.salon_id
                FROM salon_appointment sa
                LEFT JOIN salons s ON s.id = sa.salon_id
                WHERE s.deleted_at IS NULL
                  AND (:start_date IS NULL OR sa.appointment_date >= :start_date)
                  AND (:end_date IS NULL OR sa.appointment_date <= :end_date)
            ),
            cr_agg AS (
                SELECT 
                    appointment_id,
                    MAX(cancelled_by = 'user') AS by_user,
                    MAX(cancelled_by IN ('salon-facing', 'luzo-team')) AS by_salon,
                    MAX(cancelled_by = 'AUTOMATION') AS by_automation
                FROM cancellation_reasons
                GROUP BY appointment_id
            )
            SELECT 
                COUNT(*) AS total_appointments,
                SUM(CASE WHEN a.is_served = 1 THEN 1 ELSE 0 END) AS total_completed_appointments,
                SUM(CASE WHEN a.is_cancelled = 1 THEN 1 ELSE 0 END) AS total_cancelled_appointments,
                SUM(CASE WHEN a.is_served = 0 THEN COALESCE(cr.by_user, 0) ELSE 0 END) AS total_cancelled_by_user,
                SUM(CASE WHEN a.is_served = 0 THEN COALESCE(cr.by_salon, 0) ELSE 0 END) AS total_cancelled_by_salon,
                SUM(CASE WHEN a.is_served = 0 THEN COALESCE(cr.by_automation, 0) ELSE 0 END) AS total_cancelled_by_automation
            FROM base_appointments a
            LEFT JOIN cr_agg cr ON a.id = cr.appointment_id
        """)

        # Execute the database session asynchronously
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                query,
                {
                    "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
                    "end_date": end_date.strftime("%Y-%m-%d") if end_date else None
                }
            )
            # Retrieve the aggregate result row
            data = result.fetchone()

        # Parse output data row parameters
        total = int(data[0]) if data and data[0] is not None else 0
        total_completed = int(data[1]) if data and data[1] is not None else 0
        total_cancelled = int(data[2]) if data and data[2] is not None else 0
        cancelled_by_user = int(data[3]) if data and data[3] is not None else 0
        cancelled_by_salon = int(data[4]) if data and data[4] is not None else 0
        cancelled_by_automation = int(data[5]) if data and data[5] is not None else 0

        # Percentage calculator helper
        def get_percentage(val: int) -> float:
            return round((val / total) * 100, 2) if total > 0 else 0.0

        headers = [
            'Total Appointments',
            'Total Completed Appointments',
            'Completed Appointments (%)',
            'Total Cancelled Appointments',
            'Cancelled Appointments (%)',
            'Total Cancelled By User',
            'Cancelled By User (%)',
            'Total Cancelled By Salon',
            'Cancelled By Salon (%)',
            'Total Cancelled By Automation',
            'Cancelled By Automation (%)'
        ]

        row_data = [
            total,
            total_completed,
            get_percentage(total_completed),
            total_cancelled,
            get_percentage(total_cancelled),
            cancelled_by_user,
            get_percentage(cancelled_by_user),
            cancelled_by_salon,
            get_percentage(cancelled_by_salon),
            cancelled_by_automation,
            get_percentage(cancelled_by_automation)
        ]

        # Write calculations output directly into the S3/ZIP stream writer
        writer = cls.get_csv_writer(output_file, headers, **kwargs)
        writer.writerow(headers)
        writer.writerow(row_data)
