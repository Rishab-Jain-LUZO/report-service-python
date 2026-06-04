import csv
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class SalonWiseAppointmentsExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        # Construct SQL matching Laravel's getSalonAppointmentAndDetailsQuery
        query = text("""
            SELECT 
                s.id,
                s.salon_name,
                s.salon_location,
                s.city,
                s.is_disabled,
                s.partner_code,
                COUNT(sa.id) AS no_of_appointments,
                SUM(CASE WHEN sa.is_served = 1 THEN 1 ELSE 0 END) AS no_of_completed_appointments,
                SUM(CASE WHEN sa.is_cancelled = 1 THEN 1 ELSE 0 END) AS no_of_cancelled_appointments,
                SUM(CASE WHEN sa.is_served = 0 THEN COALESCE(cr.by_user, 0) ELSE 0 END) AS cancelled_by_user,
                SUM(CASE WHEN sa.is_served = 0 THEN COALESCE(cr.by_salon, 0) ELSE 0 END) AS cancelled_by_salon,
                SUM(CASE WHEN sa.is_served = 0 THEN COALESCE(cr.by_automation, 0) ELSE 0 END) AS cancelled_by_automation
            FROM salon_appointment sa
            LEFT JOIN (
                SELECT 
                    appointment_id,
                    MAX(cancelled_by = 'user') AS by_user,
                    MAX(cancelled_by IN ('salon-facing', 'luzo-team')) AS by_salon,
                    MAX(cancelled_by = 'AUTOMATION') AS by_automation
                FROM cancellation_reasons
                GROUP BY appointment_id
            ) cr ON sa.id = cr.appointment_id
            LEFT JOIN salons s ON s.id = sa.salon_id
            WHERE s.deleted_at IS NULL
              AND (:start_date IS NULL OR sa.appointment_date >= :start_date)
              AND (:end_date IS NULL OR sa.appointment_date <= :end_date)
            GROUP BY s.id, s.salon_name, s.salon_location, s.city, s.is_disabled, s.partner_code
            ORDER BY s.is_disabled ASC, s.salon_name ASC, s.id ASC
        """)

        headers = [
            'Code',
            'Partner ID',
            'Partner Name',
            'Partner Location',
            'City',
            'Is Disabled',
            'Total Appointments',
            'Completed Appointments',
            'Completed Appointments (%)',
            'Cancelled Appointments',
            'Cancelled Appointments (%)',
            'Cancelled by User',
            'Cancelled by User (%)',
            'Cancelled by Partner',
            'Cancelled by Partner (%)',
            'Cancelled by Automation',
            'Cancelled by Automation (%)'
        ]

        # Connect to database session
        async with AsyncSessionLocal() as session:
            # We obtain raw connection to execute streaming
            conn = await session.connection()
            result_stream = await conn.stream(
                query,
                {
                    "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
                    "end_date": end_date.strftime("%Y-%m-%d") if end_date else None
                }
            )

            # Open output writer targeting the stream directly
            writer = csv.writer(output_file)
            writer.writerow(headers)

            # Process database results in partitions of 1000 rows
            processed_count = 0
            async for partition in result_stream.partitions(1000):
                for row in partition:
                    total = int(row.no_of_appointments) if row.no_of_appointments else 0
                    
                    # Helper for percentages computation
                    def get_percentage(val: int) -> float:
                        return round((val / total) * 100, 2) if total > 0 else 0.0

                    completed = int(row.no_of_completed_appointments) if row.no_of_completed_appointments else 0
                    cancelled = int(row.no_of_cancelled_appointments) if row.no_of_cancelled_appointments else 0
                    by_user = int(row.cancelled_by_user) if row.cancelled_by_user else 0
                    by_salon = int(row.cancelled_by_salon) if row.cancelled_by_salon else 0
                    by_automation = int(row.cancelled_by_automation) if row.cancelled_by_automation else 0

                    writer.writerow([
                        row.partner_code,
                        row.id,
                        row.salon_name,
                        row.salon_location,
                        row.city,
                        'Yes' if row.is_disabled else 'No',
                        total,
                        completed,
                        get_percentage(completed),
                        cancelled,
                        get_percentage(cancelled),
                        by_user,
                        get_percentage(by_user),
                        by_salon,
                        get_percentage(by_salon),
                        by_automation,
                        get_percentage(by_automation)
                    ])
                processed_count += len(partition)
                if progress_callback:
                    await progress_callback(processed_count)
