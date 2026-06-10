import gc
import asyncio
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter

class LeadListExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        payload = kwargs.get("payload", {}) or {}

        # 1. Parse status list
        status = payload.get("status")
        statuses = []
        if status is not None:
            if isinstance(status, list):
                statuses = [int(s) for s in status]
            else:
                statuses = [int(status)]

        # 2. Build dynamically compiled headings
        headings = [
            'Lead Id',
            'Lead Name',
            'Assignee Id',
            'Assignee Name',
            'Contact Name',
            'Contact Number',
            'City',
            'No. Of Outlets',
            'Gst Registered',
            'Gst Percentage',
            'Entity Type',
            'Service Provided',
            'Area',
            'Pincode',
            'Google Map Link'
        ]

        status_extras = {
            1: ['Notes'],
            2: ['Rejection Reasons', 'Profile Created', 'Notes'],
            3: ['Rejection Reasons', 'Profile Created', 'Notes'],
            4: ['Salon Head Id', 'Salon Head Name', 'Salon Id', 'Salon Name', 'Salon Location', 'Salon City', 'Notes'],
            13: ['Salon Head Id', 'Salon Head Name', 'Salon Id', 'Salon Name', 'Salon Location', 'Salon City', 'Notes'],
            5: ['Salon Head Id', 'Salon Head Name', 'Scheme', 'Salon Id', 'Salon Name', 'Salon Location', 'Salon City', 'Is Salon Checked', 'Is Salon Trained', 'Is Request Invoice', 'Is Payment Route Set', 'Notes']
        }

        extras_needed = []
        for st in statuses:
            for extra in status_extras.get(st, []):
                if extra not in extras_needed:
                    extras_needed.append(extra)

        headings.extend(extras_needed)
        headings.extend(['Status', 'Source', 'Created Date', 'Status Updated At', 'Days'])

        # 3. Setup dynamic query selection
        selected_cols = payload.get("selectedColumns")
        if selected_cols:
            req_cols = {c.lower().strip() for c in selected_cols}
        else:
            req_cols = None

        def needs_col(col_name: str) -> bool:
            if req_cols is None:
                return True
            return col_name.lower().strip() in req_cols

        # 4. Build query parameters and WHERE clause
        params = {}
        where_clauses = ["l.deleted_at IS NULL"]

        if statuses:
            if len(statuses) == 1 and statuses[0] == 1:
                filter_status = payload.get("filterStatus")
                if filter_status:
                    where_clauses.append("l.status IN :status_list")
                    params["status_list"] = tuple([int(s) for s in filter_status])
                else:
                    where_clauses.append("l.status IN (1, 7, 10, 11, 12)")
            else:
                where_clauses.append("l.status IN :status_list")
                params["status_list"] = tuple(statuses)

        # Date range filters
        is_lead_created = (len(statuses) == 1 and statuses[0] == 1)
        date_col = "l.created_at" if is_lead_created else "l.status_updated_at"

        if start_date:
            where_clauses.append(f"{date_col} >= :start_date")
            params["start_date"] = start_date.strftime("%Y-%m-%d 00:00:00")
        if end_date:
            where_clauses.append(f"{date_col} <= :end_date")
            params["end_date"] = end_date.strftime("%Y-%m-%d 23:59:59")

        # Assignee filter
        assignee_ids = payload.get("assigneeIds")
        if assignee_ids:
            if isinstance(assignee_ids, list):
                has_zero = 0 in assignee_ids or "0" in assignee_ids or None in assignee_ids
                actual_ids = [int(a) for a in assignee_ids if str(a).isdigit() and int(a) != 0]
                if has_zero:
                    if actual_ids:
                        where_clauses.append("(l.assignee_id IN :assignee_ids OR l.assignee_id IS NULL)")
                        params["assignee_ids"] = tuple(actual_ids)
                    else:
                        where_clauses.append("l.assignee_id IS NULL")
                else:
                    if actual_ids:
                        where_clauses.append("l.assignee_id IN :assignee_ids")
                        params["assignee_ids"] = tuple(actual_ids)

        # Cities filter
        cities = payload.get("cities")
        if cities:
            where_clauses.append("(l.city IN :cities OR s.city IN :cities)")
            params["cities"] = tuple(cities)

        # Areas filter
        areas = payload.get("areas")
        if areas:
            where_clauses.append("(l.area IN :areas OR s.salon_area IN :areas)")
            params["areas"] = tuple(areas)

        # conversion_chance filter
        conversion_chance = payload.get("conversion_chance")
        if conversion_chance:
            where_clauses.append("l.conversion_chance IN :conversion_chance")
            params["conversion_chance"] = tuple(conversion_chance)

        # gstRegistered filter
        gst_registered = payload.get("gstRegistered")
        if gst_registered:
            pct_list = [g for g in gst_registered if g in ['18.00', '6.00', '12.00', '5.00']]
            reg_list = [g for g in gst_registered if g not in ['18.00', '6.00', '12.00', '5.00']]
            sub_clauses = []
            if pct_list:
                sub_clauses.append("l.gst_percentage IN :pct_list")
                params["pct_list"] = tuple(pct_list)
            if reg_list:
                sub_clauses.append("l.gst_registered IN :reg_list")
                params["reg_list"] = tuple(reg_list)
            if sub_clauses:
                where_clauses.append("(" + " OR ".join(sub_clauses) + ")")

        # isChecked filter
        is_checked = payload.get("isChecked")
        if is_checked is not None and is_checked != "":
            where_clauses.append("s.is_checked = :is_checked")
            params["is_checked"] = int(is_checked)

        # isTrained filter
        is_trained = payload.get("isTrained")
        if is_trained is not None and is_trained != "":
            where_clauses.append("s.training_completed = :is_trained")
            params["is_trained"] = int(is_trained)

        # isPaymentRouteSet filter
        is_payment_route_set = payload.get("isPaymentRouteSet")
        if is_payment_route_set is not None and is_payment_route_set != "":
            if int(is_payment_route_set) == 1:
                where_clauses.append("""
                    (
                        (sh.scheme = 'A' AND EXISTS (SELECT 1 FROM salon_head_tax_transactions WHERE salon_head_id = sh.id AND deleted_at IS NULL))
                        OR
                        (s.is_commissionable = 1 AND s.razorpay_vendor_account_id IS NOT NULL AND EXISTS (SELECT 1 FROM salon_commissions WHERE salon_id = s.id AND deleted_at IS NULL))
                    )
                """)
            else:
                where_clauses.append("""
                    (
                        NOT (sh.scheme = 'A' AND EXISTS (SELECT 1 FROM salon_head_tax_transactions WHERE salon_head_id = sh.id AND deleted_at IS NULL))
                        AND
                        s.razorpay_vendor_account_id IS NULL
                    )
                """)

        # searchTerm filter
        search_term = payload.get("searchTerm")
        if search_term:
            where_clauses.append("""
                (
                    l.id = :search_id
                    OR l.salon_name LIKE :search_like
                    OR l.city LIKE :search_like
                    OR l.area LIKE :search_like
                    OR EXISTS (SELECT 1 FROM contact_directories WHERE contactable_type = 'App\\\\Models\\\\Lead' AND contactable_id = l.id AND value LIKE :search_like)
                )
            """)
            params["search_id"] = int(search_term) if search_term.isdigit() else -1
            params["search_like"] = f"%{search_term}%"

        where_clause_str = " AND ".join(where_clauses)

        # Order by clauses
        order_clauses = []
        if payload.get("noOfOutlet"):
            order_clauses.append(f"l.no_of_outlets {payload.get('noOfOutlet')}")
        if payload.get("days"):
            col = "l.created_at" if is_lead_created else "l.status_updated_at"
            order_clauses.append(f"{col} {payload.get('days')}")
        order_clauses.append("l.updated_at DESC")
        order_clauses.append("l.id DESC")
        order_by_str = ", ".join(order_clauses)

        main_query = text(f"""
            SELECT 
                l.id,
                l.salon_name,
                l.gst_registered,
                l.gst_percentage,
                l.entity_type,
                l.no_of_outlets,
                l.city,
                l.area,
                l.pincode,
                l.google_map_link,
                l.status,
                l.sourceable_id,
                l.sourceable_type,
                l.created_at,
                l.status_updated_at,
                l.assignee_id,
                l.salon_id,
                l.salon_head_id,
                l.rejection_reasons,
                l.is_request_invoice,
                u_assign.name AS assignee_name,
                sh.title AS head_title,
                sh.scheme AS head_scheme,
                s.salon_name AS outlet_name,
                s.salon_location AS outlet_location,
                s.city AS outlet_city,
                s.is_checked AS outlet_is_checked,
                s.training_completed AS outlet_training_completed,
                s.is_commissionable AS outlet_is_commissionable,
                s.razorpay_vendor_account_id AS outlet_razorpay_id
            FROM leads l
            LEFT JOIN users u_assign ON l.assignee_id = u_assign.id
            LEFT JOIN salon_heads sh ON l.salon_head_id = sh.id
            LEFT JOIN salons s ON l.salon_id = s.id
            WHERE {where_clause_str}
            ORDER BY {order_by_str}
        """)

        async with AsyncSessionLocal() as session:
            conn = await session.connection()

            # Execute main query
            res = await conn.execute(main_query, params)
            leads = res.fetchall()

            if not leads:
                writer = cls.get_csv_writer(output_file, headings, **kwargs)
                writer.writerow(headings)
                return

            lead_ids = tuple([l.id for l in leads])
            salon_ids = tuple(list(set([l.salon_id for l in leads if l.salon_id])))
            salon_head_ids = tuple(list(set([l.salon_head_id for l in leads if l.salon_head_id])))

            # Maps
            contact_map = {}
            services_map = {}
            notes_map = {}
            source_map = {}
            has_tax_txs = set()
            has_commissions = set()

            # Loaders
            async def load_contacts():
                q = text("""
                    SELECT contactable_id, name, value 
                    FROM contact_directories 
                    WHERE contactable_type = 'App\\\\Models\\\\Lead' 
                      AND type = 'contact' 
                      AND deleted_at IS NULL 
                      AND contactable_id IN :lead_ids
                """)
                r = await conn.execute(q, {"lead_ids": lead_ids})
                for row in r.fetchall():
                    if row.contactable_id not in contact_map:
                        contact_map[row.contactable_id] = []
                    contact_map[row.contactable_id].append(row)

            async def load_services():
                q = text("""
                    SELECT lsp.lead_id, sp.name 
                    FROM lead_service_provided lsp 
                    JOIN service_provided sp ON lsp.service_provided_id = sp.id 
                    WHERE lsp.lead_id IN :lead_ids
                """)
                r = await conn.execute(q, {"lead_ids": lead_ids})
                for row in r.fetchall():
                    if row.lead_id not in services_map:
                        services_map[row.lead_id] = []
                    services_map[row.lead_id].append(row.name)

            async def load_latest_notes():
                q = text("""
                    SELECT ln.lead_id, ln.notes 
                    FROM lead_notes ln 
                    INNER JOIN (
                        SELECT lead_id, MAX(id) AS max_id 
                        FROM lead_notes 
                        WHERE deleted_at IS NULL AND lead_id IN :lead_ids
                        GROUP BY lead_id
                    ) latest ON latest.lead_id = ln.lead_id AND latest.max_id = ln.id
                """)
                r = await conn.execute(q, {"lead_ids": lead_ids})
                for row in r.fetchall():
                    notes_map[row.lead_id] = row.notes

            async def load_sources():
                source_user_ids = tuple(list(set([l.sourceable_id for l in leads if l.sourceable_type == "App\\Models\\User"])))
                source_lead_source_ids = tuple(list(set([l.sourceable_id for l in leads if l.sourceable_type == "App\\Models\\LeadSource"])))
                
                if source_user_ids:
                    q = text("SELECT id, name FROM users WHERE id IN :ids")
                    r = await conn.execute(q, {"ids": source_user_ids})
                    for row in r.fetchall():
                        source_map[("App\\Models\\User", row.id)] = row.name
                if source_lead_source_ids:
                    q = text("SELECT id, name FROM lead_sources WHERE id IN :ids")
                    r = await conn.execute(q, {"ids": source_lead_source_ids})
                    for row in r.fetchall():
                        source_map[("App\\Models\\LeadSource", row.id)] = row.name

            async def load_paid_route_data():
                nonlocal has_tax_txs, has_commissions
                if salon_head_ids:
                    q = text("SELECT DISTINCT salon_head_id FROM salon_head_tax_transactions WHERE deleted_at IS NULL AND salon_head_id IN :ids")
                    r = await conn.execute(q, {"ids": salon_head_ids})
                    has_tax_txs = {row.salon_head_id for row in r.fetchall()}
                if salon_ids:
                    q = text("SELECT DISTINCT salon_id FROM salon_commissions WHERE deleted_at IS NULL AND salon_id IN :ids")
                    r = await conn.execute(q, {"ids": salon_ids})
                    has_commissions = {row.salon_id for row in r.fetchall()}

            # Run needed loaders
            tasks = []
            if needs_col("Contact Name") or needs_col("Contact Number"):
                tasks.append(load_contacts())
            if needs_col("Service Provided"):
                tasks.append(load_services())
            if needs_col("Notes"):
                tasks.append(load_latest_notes())
            if needs_col("Source"):
                tasks.append(load_sources())
            if needs_col("Is Payment Route Set"):
                tasks.append(load_paid_route_data())

            if tasks:
                await asyncio.gather(*tasks)

            # Write header
            writer = cls.get_csv_writer(output_file, headings, **kwargs)
            writer.writerow(headings)

            gc.disable()
            try:
                processed_count = 0
                chunk_size = 1000
                for i in range(0, len(leads), chunk_size):
                    chunk = leads[i:i + chunk_size]
                    rows_to_write = []
                    for row in chunk:
                        lead_id = row.id

                        # Contacts
                        contacts = contact_map.get(lead_id, [])
                        contact_names = ", ".join([c.name for c in contacts if c.name]) or "Na"
                        contact_values = ", ".join([c.value for c in contacts if c.value]) or "Na"

                        # GST
                        gst_val = row.gst_registered
                        if str(gst_val).isdigit():
                            gst_label = {1: "Yes", 2: "No", 3: "Maybe"}.get(int(gst_val), "NA")
                        elif gst_val:
                            gst_label = str(gst_val).capitalize()
                        else:
                            gst_label = "NA"

                        # Entity type
                        ent_val = row.entity_type
                        if str(ent_val).isdigit():
                            ent_label = {1: "Company", 2: "Franchisee"}.get(int(ent_val), str(ent_val))
                        elif ent_val:
                            ent_label = str(ent_val)
                        else:
                            ent_label = "Na"

                        # Services
                        services_str = ", ".join(services_map.get(lead_id, [])) or "Na"

                        # Base values
                        row_data = [
                            lead_id,
                            row.salon_name or "Na",
                            row.assignee_id or "Na",
                            row.assignee_name or "Na",
                            contact_names,
                            contact_values,
                            row.city or "Na",
                            row.no_of_outlets or "Na",
                            gst_label,
                            row.gst_percentage or "Na",
                            ent_label,
                            services_str,
                            row.area or "Na",
                            row.pincode or "Na",
                            row.google_map_link or "Na"
                        ]

                        # Extra columns
                        for col in extras_needed:
                            if col == 'Notes':
                                if row.status in [1, 2, 3, 4, 5, 13, 7, 10, 12]:
                                    row_data.append(notes_map.get(lead_id, "Na") or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Rejection Reasons':
                                if row.status in [2, 3]:
                                    row_data.append(row.rejection_reasons or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Profile Created':
                                if row.status in [2, 3]:
                                    row_data.append("Yes" if row.salon_id else "No")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon Head Id':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.salon_head_id or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon Head Name':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.head_title or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Scheme':
                                if row.status in [5]:
                                    row_data.append(row.head_scheme or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon Id':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.salon_id or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon Name':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.outlet_name or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon Location':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.outlet_location or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Salon City':
                                if row.status in [4, 5, 13]:
                                    row_data.append(row.outlet_city or "Na")
                                else:
                                    row_data.append("Na")
                            elif col == 'Is Salon Checked':
                                if row.status in [5]:
                                    row_data.append("Yes" if row.outlet_is_checked else "No")
                                else:
                                    row_data.append("Na")
                            elif col == 'Is Salon Trained':
                                if row.status in [5]:
                                    row_data.append("Yes" if row.outlet_training_completed else "No")
                                else:
                                    row_data.append("Na")
                            elif col == 'Is Request Invoice':
                                if row.status in [5]:
                                    row_data.append("Yes" if row.is_request_invoice == 1 else "No")
                                else:
                                    row_data.append("Na")
                            elif col == 'Is Payment Route Set':
                                if row.status in [5]:
                                    paid_route = 0
                                    if row.salon_id and row.salon_head_id:
                                        if row.head_scheme == "A" and row.salon_head_id in has_tax_txs:
                                            paid_route = 1
                                        elif (row.head_scheme == "B" and 
                                              row.outlet_is_commissionable == 1 and 
                                              row.outlet_razorpay_id and 
                                              row.salon_id in has_commissions):
                                            paid_route = 1
                                    row_data.append("Yes" if paid_route else "No")
                                else:
                                    row_data.append("Na")

                        # End columns
                        status_labels = {
                            1: "Lead Created",
                            2: "Rejected By Us",
                            3: "Rejected By Them",
                            4: "In The Making",
                            5: "In The Training",
                            6: "Converted",
                            7: "Initiated Conversation",
                            10: "Awaiting Details",
                            11: "Others",
                            12: "Didn't Answer",
                            13: "On Hold"
                        }
                        status_label = status_labels.get(row.status, str(row.status))
                        row_data.append(status_label)

                        source_name = source_map.get((row.sourceable_type, row.sourceable_id), "Na")
                        row_data.append(source_name)

                        c_date = row.created_at.strftime("%Y-%m-%d") if row.created_at else "Na"
                        row_data.append(c_date)

                        u_date = row.status_updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.status_updated_at else "Na"
                        row_data.append(u_date)

                        if row.status_updated_at:
                            days_val = (datetime.utcnow().date() - row.status_updated_at.date()).days
                        else:
                            days_val = 0
                        row_data.append(days_val)

                        rows_to_write.append(row_data)

                    writer.writerows(rows_to_write)
                    processed_count += len(chunk)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
