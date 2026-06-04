import csv
from datetime import datetime, timedelta
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class AllAppointmentsExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        import gc
        # Construct raw SQL query to fetch appointment details with pre-formatted date strings
        # and pre-calculated time differences to offload CPU load from Python to MySQL.
        query = text("""
            SELECT 
                sa.id,
                sa.salon_id,
                s.salon_name,
                s.salon_location,
                s.city,
                s.outlet_type,
                c.id AS customer_id,
                c.name AS customer_name,
                c.contact AS customer_contact,
                c.gender AS customer_gender,
                DATE_FORMAT(sa.appointment_date, '%Y-%m-%d') AS app_date,
                sa.appointment_time AS app_time,
                DATE_FORMAT(sa.created_at, '%Y-%m-%d') AS booking_date,
                DATE_FORMAT(sa.created_at, '%I:%M %p') AS booking_time,
                sa.status,
                sa.confirmed_at,
                sa.is_served,
                sa.is_cancelled,
                sa.appointment_source,
                sa.appointment_in_working_hours,
                TIMESTAMPDIFF(MINUTE, sa.created_at, CONCAT(sa.appointment_date, ' ', sa.appointment_time)) AS advance_minutes
            FROM salon_appointment sa
            INNER JOIN salons s ON s.id = sa.salon_id AND s.deleted_at IS NULL
            LEFT JOIN customers c ON c.id = sa.customer_id
            WHERE (:start_date IS NULL OR sa.created_at >= :start_date)
              AND (:end_date IS NULL OR sa.created_at <= :end_date)
            ORDER BY sa.id DESC
        """)

        headers = [
            'Appointment ID',
            'Salon Id',
            'Partner Name',
            'Partner Location',
            'Partner City',
            'Outlet Type',
            'Customer Id',
            'Customer Name',
            'Customer Contact',
            'Customer Gender',
            'Customer No. of Payments',
            'Partner Category',
            'Growth Manager',
            'Appointment Date',
            'Appointment Time',
            'Booking Date',
            'Booking Time',
            'First Action Taken By',
            'First Action Taken At',
            'First Action Taken In (Time from Booking in minutes)',
            'First Action Status',
            'Advance Booking Time (in minutes)',
            'Booked in working hours',
            'Current Status',
            'Was Confirmed',
            'Served',
            'Cancelled',
            'Cancellation Reason',
            'Cancelled By',
            'Cancelled At',
            'Was Customer near Outlet',
            'Distance from Outlet (mtrs)',
            'Appointment Source'
        ]

        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            result_stream = await conn.stream(
                query,
                {
                    "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
                    "end_date": end_date.strftime("%Y-%m-%d") if end_date else None
                }
            )

            # Create output writer targeting the stream directly
            writer = csv.writer(output_file)
            writer.writerow(headers)

            # Disable garbage collection temporarily to optimize tight loop execution speed
            gc.disable()
            try:
                processed_count = 0
                async for partition in result_stream.partitions(1000):
                    # Write in bulk chunks of 1000 rows to minimize individual writerow function calls in Python
                    rows_to_write = [
                        [
                            row.id,
                            row.salon_id,
                            row.salon_name,
                            row.salon_location,
                            row.city,
                            row.outlet_type,
                            row.customer_id,
                            row.customer_name,
                            row.customer_contact,
                            row.customer_gender,
                            0,  # total payments placeholder
                            "", # categories placeholder
                            "", # manager placeholder
                            row.app_date or "",
                            row.app_time or "",
                            row.booking_date or "",
                            row.booking_time or "",
                            "", # first action by placeholder
                            "", # first action at placeholder
                            "", # first action in mins placeholder
                            "", # first action status placeholder
                            row.advance_minutes if row.advance_minutes is not None else "",
                            'Yes' if row.appointment_in_working_hours else 'No',
                            row.status,
                            'Yes' if row.confirmed_at else 'No',
                            'Yes' if row.is_served else 'No',
                            'Yes' if row.is_cancelled else 'No',
                            "", # cancellation reason
                            "", # cancelled by
                            "", # cancelled at
                            "NA", # customer proximity
                            "", # distance
                            row.appointment_source
                        ]
                        for row in partition
                    ]
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
