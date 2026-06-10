import csv
from datetime import datetime, timedelta
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter
from core.columns import ALL_APPOINTMENTS_HEADERS, all_appointments_needs_customer

class AllAppointmentsExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        import gc
        
        # Determine requested columns
        selected_columns = kwargs.get("payload", {}).get("selectedColumns")
        need_customer = all_appointments_needs_customer(selected_columns)

        select_fields = [
            "sa.id",
            "sa.salon_id",
            "s.salon_name",
            "s.salon_location",
            "s.city",
            "s.outlet_type",
            "DATE_FORMAT(sa.appointment_date, '%Y-%m-%d') AS app_date",
            "sa.appointment_time AS app_time",
            "DATE_FORMAT(sa.created_at, '%Y-%m-%d') AS booking_date",
            "DATE_FORMAT(sa.created_at, '%I:%M %p') AS booking_time",
            "sa.status",
            "sa.confirmed_at",
            "sa.is_served",
            "sa.is_cancelled",
            "sa.appointment_source",
            "sa.appointment_in_working_hours",
            "TIMESTAMPDIFF(MINUTE, sa.created_at, CONCAT(sa.appointment_date, ' ', sa.appointment_time)) AS advance_minutes"
        ]

        if need_customer:
            select_fields.extend([
                "c.id AS customer_id",
                "c.name AS customer_name",
                "c.contact AS customer_contact",
                "c.gender AS customer_gender"
            ])

        joins = ["INNER JOIN salons s ON s.id = sa.salon_id AND s.deleted_at IS NULL"]
        if need_customer:
            joins.append("LEFT JOIN customers c ON c.id = sa.customer_id")

        select_clause = ",\n                ".join(select_fields)
        joins_clause = "\n            ".join(joins)

        # Construct raw SQL query dynamically
        query = text(f"""
            SELECT 
                {select_clause}
            FROM salon_appointment sa
            {joins_clause}
            WHERE (:start_date IS NULL OR sa.created_at >= :start_date)
              AND (:end_date IS NULL OR sa.created_at <= :end_date)
            ORDER BY sa.id DESC
        """)

        headers = ALL_APPOINTMENTS_HEADERS

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
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
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
                            getattr(row, "customer_id", None) or "",
                            getattr(row, "customer_name", None) or "",
                            getattr(row, "customer_contact", None) or "",
                            getattr(row, "customer_gender", None) or "",
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

