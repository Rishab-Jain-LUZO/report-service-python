import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter
from core.columns import PARTNER_RM_LIST_HEADERS

class PartnerRmListExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {})

        # Build query parameters and WHERE clause
        params = {}
        where_clauses = ["s.deleted_at IS NULL"]

        # 1. status
        status = payload.get("status")
        if status is not None and status != "":
            where_clauses.append("s.is_disabled = :status")
            params["status"] = int(status)

        # 2. searchTerm
        search_term = payload.get("searchTerm")
        if search_term:
            where_clauses.append("(s.id = :search_id OR s.search_data LIKE :search_like)")
            params["search_id"] = int(search_term) if search_term.isdigit() else -1
            params["search_like"] = f"%{search_term}%"

        # 3. rm_id
        rm_ids = payload.get("rm_id", [])
        if isinstance(rm_ids, str):
            rm_ids = [int(r.strip()) for r in rm_ids.split(",") if r.strip().isdigit()]
        elif isinstance(rm_ids, list):
            rm_ids = [int(r) for r in rm_ids if str(r).isdigit()]

        if rm_ids:
            has_zero = 0 in rm_ids
            actual_rm_ids = [r for r in rm_ids if r != 0]

            if has_zero and not actual_rm_ids:
                where_clauses.append("s.id NOT IN (SELECT salon_id FROM rm_salon)")
            elif not has_zero and actual_rm_ids:
                where_clauses.append("s.id IN (SELECT salon_id FROM rm_salon WHERE rm_id IN :rm_ids)")
                params["rm_ids"] = tuple(actual_rm_ids)
            elif has_zero and actual_rm_ids:
                where_clauses.append("(s.id NOT IN (SELECT salon_id FROM rm_salon) OR s.id IN (SELECT salon_id FROM rm_salon WHERE rm_id IN :rm_ids))")
                params["rm_ids"] = tuple(actual_rm_ids)

        where_clause_str = " AND ".join(where_clauses)

        main_query = text(f"""
            SELECT 
                s.id,
                s.salon_name,
                s.salon_location,
                s.outlet_type,
                s.is_disabled,
                s.enable_date,
                s.confirmation_rate,
                s.cancellation_rate,
                s.salon_head_id,
                sh.title AS head_title,
                sh.scheme AS head_scheme,
                sh.balance_poc_at_luzo AS head_poc
            FROM salons s
            LEFT JOIN salon_heads sh ON s.salon_head_id = sh.id
            WHERE {where_clause_str}
            ORDER BY s.id ASC
        """)

        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            
            # 1. Fetch matching salons
            salons_result = await conn.execute(main_query, params)
            salons = salons_result.fetchall()

            if not salons:
                # No salons match, just write headers and exit
                headers = PARTNER_RM_LIST_HEADERS
                writer = cls.get_csv_writer(output_file, headers, **kwargs)
                writer.writerow(headers)
                return

            salon_ids = tuple([s.id for s in salons])
            salon_head_ids = tuple(list(set([s.salon_head_id for s in salons if s.salon_head_id is not None])))

            date_params = {
                "start_date": start_date.strftime("%Y-%m-%d 00:00:00") if start_date else None,
                "end_date": end_date.strftime("%Y-%m-%d 23:59:59") if end_date else None
            }

            # Pre-fetch maps
            rm_map = {}
            cat_map = {}
            wallet_map = {}
            tax_map = {}
            contact_map = {}
            appointments_map = {}
            payments_map = {}
            completed_map = {}
            pnl_map = {}
            abv_map = {}
            notes_map = {}

            # Helper functions to run query and populate dictionary
            async def load_rm_names():
                q = text("SELECT rms.salon_id, GROUP_CONCAT(u.name SEPARATOR ', ') AS names FROM rm_salon rms JOIN users u ON rms.rm_id = u.id WHERE rms.salon_id IN :salon_ids GROUP BY rms.salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids})
                for row in res.fetchall():
                    rm_map[row.salon_id] = row.names

            async def load_categories():
                q = text("SELECT sca.salon_id, GROUP_CONCAT(sc.name SEPARATOR ', ') AS names FROM salon_category_associations sca JOIN salon_categories sc ON sca.salon_category_id = sc.id WHERE sca.salon_id IN :salon_ids GROUP BY sca.salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids})
                for row in res.fetchall():
                    cat_map[row.salon_id] = row.names

            async def load_wallet_balances():
                if not salon_head_ids:
                    return
                q = text("SELECT shw.salon_head_id, SUM(shw.balance) AS total_balance FROM salon_head_wallets shw WHERE shw.salon_head_id IN :salon_head_ids AND shw.is_archived = 0 AND shw.deleted_at IS NULL GROUP BY shw.salon_head_id")
                res = await conn.execute(q, {"salon_head_ids": salon_head_ids})
                for row in res.fetchall():
                    wallet_map[row.salon_head_id] = row.total_balance

            async def load_tax_transactions():
                if not salon_head_ids:
                    return
                q = text("""
                    SELECT t.salon_head_id, t.package_amount_with_gst, t.benefit_received, t.margin_received
                    FROM salon_head_tax_transactions t
                    INNER JOIN (
                        SELECT salon_head_id, MAX(id) AS max_id
                        FROM salon_head_tax_transactions
                        WHERE salon_head_id IN :salon_head_ids AND deleted_at IS NULL
                        GROUP BY salon_head_id
                    ) latest ON latest.salon_head_id = t.salon_head_id AND latest.max_id = t.id
                """)
                res = await conn.execute(q, {"salon_head_ids": salon_head_ids})
                for row in res.fetchall():
                    tax_map[row.salon_head_id] = row

            async def load_contacts():
                if not salon_head_ids:
                    return
                q = text("SELECT salon_head_id, GROUP_CONCAT(CONCAT_WS(' | ', NULLIF(name, ''), NULLIF(contact, '')) SEPARATOR '; ') AS contacts FROM salon_head_contacts_directory WHERE salon_head_id IN :salon_head_ids AND deleted_at IS NULL GROUP BY salon_head_id")
                res = await conn.execute(q, {"salon_head_ids": salon_head_ids})
                for row in res.fetchall():
                    contact_map[row.salon_head_id] = row.contacts

            async def load_appointments_count():
                q = text("SELECT salon_id, COUNT(*) AS cnt FROM salon_appointment WHERE salon_id IN :salon_ids AND (:start_date IS NULL OR appointment_date >= :start_date) AND (:end_date IS NULL OR appointment_date <= :end_date) GROUP BY salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids, **date_params})
                for row in res.fetchall():
                    appointments_map[row.salon_id] = row.cnt

            async def load_payments_count_and_billing():
                q = text("SELECT salon_id, COUNT(*) AS cnt, SUM(total_price) AS total_billing FROM salonsurf_pro_payments WHERE salon_id IN :salon_ids AND (:start_date IS NULL OR created_at >= :start_date) AND (:end_date IS NULL OR created_at <= :end_date) GROUP BY salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids, **date_params})
                for row in res.fetchall():
                    payments_map[row.salon_id] = (row.cnt, row.total_billing)

            async def load_completed_appointments():
                q = text("""
                    SELECT a.salon_id, COUNT(*) AS cnt
                    FROM (
                        SELECT sa.salon_id, DATE(sa.appointment_date) AS ad, sa.customer_id, MAX(sa.is_served) AS max_served
                        FROM salon_appointment sa
                        WHERE sa.salon_id IN :salon_ids
                          AND (:start_date IS NULL OR sa.appointment_date >= :start_date) 
                          AND (:end_date IS NULL OR sa.appointment_date <= :end_date)
                        GROUP BY sa.salon_id, DATE(sa.appointment_date), sa.customer_id
                    ) a
                    WHERE a.max_served = 1
                    GROUP BY a.salon_id
                """)
                res = await conn.execute(q, {"salon_ids": salon_ids, **date_params})
                for row in res.fetchall():
                    completed_map[row.salon_id] = row.cnt

            async def load_lifetime_abv():
                q = text("SELECT salon_id, AVG(total_price) AS avg_abv FROM salonsurf_pro_payments WHERE salon_id IN :salon_ids GROUP BY salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids})
                for row in res.fetchall():
                    abv_map[row.salon_id] = row.avg_abv

            async def load_pnl():
                q = text("SELECT salon_id, SUM(pnl) AS total_pnl FROM salon_head_passbooks WHERE salon_id IN :salon_ids AND deleted_at IS NULL AND (:start_date IS NULL OR txn_date >= :start_date) AND (:end_date IS NULL OR txn_date <= :end_date) GROUP BY salon_id")
                res = await conn.execute(q, {"salon_ids": salon_ids, **date_params})
                for row in res.fetchall():
                    pnl_map[row.salon_id] = row.total_pnl

            async def load_latest_note():
                q = text("""
                    SELECT n.noteable_id AS salon_id, CONCAT(n.notes, IF(u.name IS NOT NULL, CONCAT(' (by: ', u.name, ')'), ''), ' at ', DATE_FORMAT(n.created_at, '%Y-%m-%d %H:%i:%s')) AS formatted_note
                    FROM notes n
                    LEFT JOIN users u ON n.created_by = u.id
                    INNER JOIN (
                        SELECT noteable_id, MAX(id) AS max_id
                        FROM notes
                        WHERE noteable_type = 'App\\\\Models\\\\Salon' AND noteable_id IN :salon_ids AND deleted_at IS NULL
                        GROUP BY noteable_id
                    ) latest ON latest.noteable_id = n.noteable_id AND latest.max_id = n.id
                """)
                res = await conn.execute(q, {"salon_ids": salon_ids})
                for row in res.fetchall():
                    notes_map[row.salon_id] = row.formatted_note

            # Determine which loaders are needed based on selected columns
            selected_cols = payload.get("selectedColumns")
            if selected_cols:
                req_cols = {c.lower().strip() for c in selected_cols}
            else:
                req_cols = None

            def needs_col(col_name: str) -> bool:
                if req_cols is None:
                    return True
                return col_name.lower().strip() in req_cols

            # Execute only the needed pre-fetch tasks
            tasks = []
            if needs_col("RM name"):
                tasks.append(load_rm_names())
            if needs_col("Partner Category"):
                tasks.append(load_categories())
            if needs_col("Wallet Balance"):
                tasks.append(load_wallet_balances())
            if needs_col("Tax: Package Amount") or needs_col("Tax: Benefit Received") or needs_col("Tax: Margin Received"):
                tasks.append(load_tax_transactions())
            if needs_col("Partner POC"):
                tasks.append(load_contacts())
            if needs_col("Appointments Count"):
                tasks.append(load_appointments_count())
            if needs_col("Payments Count") or needs_col("Total Billing"):
                tasks.append(load_payments_count_and_billing())
            if needs_col("Total Completed Appointments"):
                tasks.append(load_completed_appointments())
            if needs_col("Life Time ABV"):
                tasks.append(load_lifetime_abv())
            if needs_col("PNL"):
                tasks.append(load_pnl())
            if needs_col("Latest RM Notes"):
                tasks.append(load_latest_note())

            import asyncio
            if tasks:
                await asyncio.gather(*tasks)

            # Write header
            headers = PARTNER_RM_LIST_HEADERS
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            gc.disable()
            try:
                processed_count = 0
                chunk_size = 1000
                for i in range(0, len(salons), chunk_size):
                    chunk = salons[i:i + chunk_size]
                    rows_to_write = []
                    for row in chunk:
                        # Format enable/starting date
                        ed = getattr(row, "enable_date", None)
                        ed_str = ed.strftime("%Y-%m-%d") if ed else "-"

                        # Lookups in dictionaries
                        s_id = row.id
                        sh_id = row.salon_head_id

                        pay_stats = payments_map.get(s_id, (0, 0.0))
                        payments_cnt = pay_stats[0]
                        total_billing_val = pay_stats[1]

                        tb_str = f"{float(total_billing_val):.2f}" if total_billing_val is not None else "0.00"

                        abv_val = abv_map.get(s_id, 0.0)
                        abv_str = f"{float(abv_val):.2f}" if abv_val is not None else "0.00"

                        pnl_val = pnl_map.get(s_id, 0.0)
                        pnl_str = f"{float(pnl_val):.2f}" if pnl_val is not None else "0.00"

                        hb_val = wallet_map.get(sh_id, 0.0) if sh_id else 0.0
                        hb_str = f"{float(hb_val):.2f}" if hb_val is not None else "0.00"

                        tax_tx = tax_map.get(sh_id) if sh_id else None
                        pkg_val = getattr(tax_tx, "package_amount_with_gst", None) if tax_tx else None
                        pkg_str = f"{float(pkg_val):.2f}" if pkg_val is not None else "-"

                        ben_val = getattr(tax_tx, "benefit_received", None) if tax_tx else None
                        ben_str = f"{float(ben_val):.2f}" if ben_val is not None else "-"

                        marg_val = getattr(tax_tx, "margin_received", None) if tax_tx else None
                        marg_str = f"{float(marg_val):.2f}" if marg_val is not None else "-"

                        rows_to_write.append([
                            s_id,
                            getattr(row, "salon_name", "-") or "-",
                            getattr(row, "salon_location", "-") or "-",
                            getattr(row, "outlet_type", "-") or "-",
                            "Disabled" if getattr(row, "is_disabled", 0) else "Enabled",
                            getattr(row, "head_title", "-") or "-",
                            getattr(row, "head_scheme", "-") or "-",
                            cat_map.get(s_id, "-") or "-",
                            hb_str,
                            pkg_str,
                            ben_str,
                            marg_str,
                            contact_map.get(sh_id, "-") or "-",
                            getattr(row, "head_poc", "-") or "-",
                            rm_map.get(s_id, "-") or "-",
                            appointments_map.get(s_id, 0) or 0,
                            payments_cnt or 0,
                            completed_map.get(s_id, 0) or 0,
                            getattr(row, "confirmation_rate", 0) or 0,
                            getattr(row, "cancellation_rate", 0) or 0,
                            tb_str,
                            abv_str,
                            pnl_str,
                            notes_map.get(s_id, "-") or "-",
                            ed_str
                        ])
                    
                    writer.writerows(rows_to_write)
                    processed_count += len(chunk)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
