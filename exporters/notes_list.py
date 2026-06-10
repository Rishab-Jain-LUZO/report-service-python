import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter
from core.columns import NOTES_LIST_HEADERS

class NotesListExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        # Notes query ordering by ID DESC
        query = text("""
            SELECT 
                n.noteable_type,
                n.noteable_id,
                n.salon_id,
                n.notes,
                n.created_at,
                u.name AS creator_name,
                nc.note_category_name,
                s.salon_head_id,
                s.salon_name,
                s.salon_location,
                sh.title AS head_title,
                (
                    SELECT GROUP_CONCAT(ru.name SEPARATOR ', ') 
                    FROM rm_salon rms 
                    JOIN users ru ON rms.rm_id = ru.id 
                    WHERE rms.salon_id = s.id
                ) AS regional_manager_names
            FROM notes n
            LEFT JOIN users u ON n.created_by = u.id
            LEFT JOIN note_categories nc ON n.note_category_id = nc.id
            LEFT JOIN salons s ON n.salon_id = s.id
            LEFT JOIN salon_heads sh ON s.salon_head_id = sh.id
            WHERE n.deleted_at IS NULL
            ORDER BY n.id DESC
        """)

        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            result_stream = await conn.stream(query)

            headers = NOTES_LIST_HEADERS
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            gc.disable()
            try:
                processed_count = 0
                async for partition in result_stream.partitions(1000):
                    rows_to_write = []
                    for row in partition:
                        # Determine Note Category type
                        nt_type = getattr(row, "noteable_type", "")
                        if nt_type == "App\\Models\\SalonHead":
                            note_type = "owner"
                        elif nt_type == "App\\Models\\Salon":
                            note_type = "manager"
                        elif nt_type == "App\\Models\\SalonAppointment":
                            note_type = "appointment"
                        else:
                            note_type = "unknown"

                        # Appointment ID
                        app_id = getattr(row, "noteable_id", "-") if note_type == "appointment" else "-"

                        # Created at formatting
                        c_at = getattr(row, "created_at", None)
                        c_at_str = c_at.strftime("%Y-%m-%d %H:%M") if c_at else "-"

                        rows_to_write.append([
                            getattr(row, "salon_head_id", "-") or "-",
                            getattr(row, "head_title", "-") or "-",
                            getattr(row, "salon_id", "-") or "-",
                            getattr(row, "salon_name", "-") or "-",
                            getattr(row, "salon_location", "-") or "-",
                            getattr(row, "regional_manager_names", "-") or "-",
                            note_type,
                            getattr(row, "note_category_name", "-") or "-",
                            app_id,
                            c_at_str,
                            getattr(row, "notes", "") or "",
                            getattr(row, "creator_name", "-") or "-"
                        ])
                    
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
