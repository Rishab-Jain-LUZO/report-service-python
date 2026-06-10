# Luzo Universal Report Service Documentation

Welcome to the **Luzo Universal Report Service** developer documentation. This guide is organized to help new developers understand, run, and extend the report service quickly.

---

## 1. System Overview & Architecture

The report service is a high-performance Python microservice designed to compile and export large datasets (such as Salon Head Passbook transactions and Appointments) without causing database locks or high server memory consumption.

### Key Components
- **FastAPI Layer ([main.py](file:///C:/Users/luzot/Herd/python-report-service/main.py))**: Handles HTTP requests, authentication via token headers, payload validation, and triggers asynchronous background jobs.
- **Celery Worker ([tasks.py](file:///C:/Users/luzot/Herd/python-report-service/tasks.py))**: Executes export jobs asynchronously in the background. It utilizes in-memory streams (`io.StringIO` and `io.BytesIO`) to build CSV files and compile ZIP archives, bypassing local disk I/O bottlenecks.
- **Column Configurations ([core/columns.py](file:///C:/Users/luzot/Herd/python-report-service/core/columns.py))**: Centralized catalog of report headers and table join dependency check helper functions to keep exporters modular and clean.
- **Base Exporter Registry ([core/registry.py](file:///C:/Users/luzot/Herd/python-report-service/core/registry.py))**: Registers available report classes under logical category keys (e.g., `appointments`, `salon_heads`).
- **Database Access Layer ([db.py](file:///C:/Users/luzot/Herd/python-report-service/db.py))**: Implements thread-safe, async connection pooling using SQLAlchemy and handles connection lifecycle management (`dispose_loop_engine`) to prevent connection leaks across event loops.
- **Amazon S3 & SMTP Integrations**: Uploads ZIP archives directly from RAM to AWS S3 and sends email notifications with secure download links.

---

## 2. Quick Start & API Reference

All requests must include the secret token header.

### Authentication Header
```http
X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls
```

---

### A. Trigger Export Job
Initiates a background task to compile CSV reports into a ZIP archive.

- **URL**: `/api/v1/export`
- **Method**: `POST`
- **Headers**:
  - `Content-Type: application/json`
  - `X-Report-Service-Token: <token>`

#### Request Payload Properties

| Field Name | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `category` | String | Yes | Export category. Supported: `appointments`, `salon_heads`, `regional_managers`, `leads`, `offers`, `giftcards`. |
| `reports` | Array of Strings | Yes | Specific reports to generate. |
| `startDate` | String (YYYY-MM-DD) | No | Start date filter (defaults to 180 days before endDate). |
| `endDate` | String (YYYY-MM-DD) | No | End date filter (defaults to current UTC date). |
| `email` | String (Email format) | Yes | Destination email where the download link ZIP will be sent. |
| `selectedColumns` | Array of Strings | No | **Dynamic Columns:** Columns to include in the output CSV. |
| `salonHeadIds` | Array of Integers | No | *Passbook specific:* List of Salon Head IDs to filter. |
| `salonHeadWalletIds` | Array of Integers | No | *Passbook specific:* List of Salon Head Wallet IDs to filter. |

#### Example payloads and curl commands:

##### Example 1: Appointments Export (All reports with custom columns)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "appointments",
    "reports": ["summary", "salon_wise", "all_list", "completion_rate"],
    "startDate": "2026-05-01",
    "endDate": "2026-06-01",
    "email": "luzotech@luzo.app",
    "selectedColumns": [
      "Appointment ID",
      "Partner Name",
      "Customer Name",
      "Customer Gender",
      "Current Status"
    ]
  }'
```

##### Example 2: Salon Head Passbook Export (Passbook with custom columns)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "salon_heads",
    "reports": ["passbook"],
    "startDate": "2026-05-01",
    "endDate": "2026-06-01",
    "email": "luzotech@luzo.app",
    "salonHeadIds": [1, 2, 5],
    "selectedColumns": [
      "Txn Date",
      "Recorded Head Name",
      "Final Amt",
      "Customer Name"
    ]
  }'
```

##### Example 3: Regional Manager Export (Partner list, Notes list, and Completion rate)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "regional_managers",
    "reports": ["partner_rm_list", "notes_list", "completion_rate"],
    "startDate": "2026-05-01",
    "endDate": "2026-06-01",
    "email": "luzotech@luzo.app",
    "monthLimit": 3,
    "weekLimit": 3,
    "status": 0,
    "selectedColumns": [
      "Partner Id",
      "Partner Name",
      "Wallet Balance",
      "RM name"
    ]
  }'
```

##### Example 4: Leads Export (Leads List)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "leads",
    "reports": ["leads_list"],
    "startDate": "2026-05-01",
    "endDate": "2026-06-01",
    "email": "luzotech@luzo.app",
    "status": 1
  }'
```

##### Example 5: Offers Export (General/All Offers with filters)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "offers",
    "reports": ["offers_list"],
    "email": "luzotech@luzo.app",
    "offerType": "general",
    "filters": {
      "is_active": 1,
      "is_deleted": 0,
      "searchTerm": "Kanya"
    }
  }'
```

##### Example 6: Gift Card Transactions Export (with filters)
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: qiNmMm4pF6Gb2DBLjphSxTNYB1G5CFF4g4OHFo8IKiFseUOC9MutlvNcj0ynsGls" \
  -d '{
    "category": "giftcards",
    "reports": ["transactions_list"],
    "startDate": "2026-05-01",
    "endDate": "2026-06-01",
    "email": "luzotech@luzo.app",
    "status": "CLAIMED",
    "searchTerm": "John"
  }'
```


#### Successful Trigger Response (HTTP 200)
```json
{
  "status": "success",
  "message": "Export process for 'appointments' initiated successfully.",
  "task_id": "e3826c3f-28d3-4ebb-ae69-20f36023538a"
}
```

---

### B. Check Task Status
Retrieves task progress, status messages, and execution state of a Celery job.

- **URL**: `/api/v1/export/status/{task_id}`
- **Method**: `GET`

##### Example Status Check
```bash
curl -X GET http://127.0.0.1:8000/api/v1/export/status/e3826c3f-28d3-4ebb-ae69-20f36023538a
```

##### Example Responses:
- **Pending**: `{"status": "pending", "progress": 0, "message": "Task is waiting in queue."}`
- **In Progress**: `{"status": "in_progress", "progress": 45, "message": "Generating: passbook: 12,500 rows"}`
- **Completed**: `{"status": "completed", "progress": 100, "message": "Export completed successfully.", "result": null}`
- **Failed**: `{"status": "failed", "progress": 0, "message": "OperationalError: ..."}`

---

## 3. Available Column Names for `selectedColumns`

The `selectedColumns` list is matched case-insensitively. The valid column headers for each report type are listed below:

### A. Category: `appointments`

#### 1. Report Type: `all_list` (All Appointments list)
* `Appointment ID`
* `Salon Id`
* `Partner Name`
* `Partner Location`
* `Partner City`
* `Outlet Type`
* `Customer Id`
* `Customer Name`
* `Customer Contact`
* `Customer Gender`
* `Customer No. of Payments`
* `Partner Category`
* `Growth Manager`
* `Appointment Date`
* `Appointment Time`
* `Booking Date`
* `Booking Time`
* `First Action Taken By`
* `First Action Taken At`
* `First Action Taken In (Time from Booking in minutes)`
* `First Action Status`
* `Advance Booking Time (in minutes)`
* `Booked in working hours`
* `Current Status`
* `Was Confirmed`
* `Served`
* `Cancelled`
* `Cancellation Reason`
* `Cancelled By`
* `Cancelled At`
* `Was Customer near Outlet`
* `Distance from Outlet (mtrs)`
* `Appointment Source`

#### 2. Report Type: `salon_wise` (Salon-wise aggregations)
* `Code`
* `Partner ID`
* `Partner Name`
* `Partner Location`
* `City`
* `Is Disabled`
* `Total Appointments`
* `Completed Appointments`
* `Completed Appointments (%)`
* `Cancelled Appointments`
* `Cancelled Appointments (%)`
* `Cancelled by User`
* `Cancelled by User (%)`
* `Cancelled by Partner`
* `Cancelled by Partner (%)`
* `Cancelled by Automation`
* `Cancelled by Automation (%)`

---

### B. Category: `salon_heads`

#### 1. Report Type: `passbook` (Salon Head Passbook transactions)
* `Txn Type`
* `Recorded Head Id`
* `Recorded Head Name`
* `Recorded Head Scheme`
* `Recorded Head Settlement Type`
* `Recorded Head POC`
* `Recorded Head Wallet Id`
* `Salon Id`
* `Salon Name`
* `Salon Location`
* `Salon City`
* `Growth Manager`
* `Current Head Id`
* `Current Head Name`
* `Current Head Scheme`
* `Current Head Settlement Type`
* `Current Head POC`
* `Current Wallet Id`
* `Customer Id`
* `Customer Name`
* `Contact`
* `Bill/Deposit Amount`
* `Cashback Used`
* `Discount Percentage`
* `Platform Fees`
* `Cancellation Fees`
* `GC Amt Used`
* `Amount Before PG Offers`
* `Final Amt`
* `Cashback Percentage`
* `Cashback Earned`
* `Offer Code`
* `RZP Offers Used`
* `RZP Fees`
* `PNL`
* `Gross Margin`
* `Margin/Commission %`
* `Customer Payment No`
* `Txn Date`
* `Txn Day`
* `Txn Month`
* `Txn Year`
* `RZP Id`
* `Payment Id`
* `Referral/Marketing codes used`
* `Commission Sent`
* `Commission Received`
* `Deposit Id`
* `Customer Email`
* `Customer Gender`
* `Customer DOB`
* `Customer Age`
* `Customer App Version`
* `Customer OS`
* `Customer Pincode`
* `Customer State`
* `Salon Area`
* `Salon Pincode`
* `Salon Disabled`
* `Passbook Id (Used for reconciliation)`
* `Razorpay UTR`

### C. Category: `regional_managers`

#### 1. Report Type: `partner_rm_list` (Partner Growth Manager List)
* `Partner Id`
* `Partner Name`
* `Partner Location`
* `Partner Outlet Type`
* `Partner enable status`
* `Partner Head Title`
* `Scheme`
* `Partner Category`
* `Wallet Balance`
* `Tax: Package Amount`
* `Tax: Benefit Received`
* `Tax: Margin Received`
* `Partner POC`
* `Onboarding POC`
* `RM name`
* `Appointments Count`
* `Payments Count`
* `Total Completed Appointments`
* `Confirmation Rate`
* `Cancellation Rate`
* `Total Billing`
* `Life Time ABV`
* `PNL`
* `Latest RM Notes`
* `Starting Date`

#### 2. Report Type: `notes_list` (All Growth Manager Notes)
* `Head ID`
* `Head Name`
* `Partner ID`
* `Partner Name`
* `Location`
* `Growth Manager`
* `Category`
* `Subcategory`
* `Appointment Id`
* `Date`
* `Notes`
* `Note By`

### D. Category: `leads`

#### 1. Report Type: `leads_list` (Leads List)
* `Lead Id`
* `Lead Name`
* `Assignee Id`
* `Assignee Name`
* `Contact Name`
* `Contact Number`
* `City`
* `No. Of Outlets`
* `Gst Registered`
* `Gst Percentage`
* `Entity Type`
* `Service Provided`
* `Area`
* `Pincode`
* `Google Map Link`
* `Notes`
* `Rejection Reasons`
* `Profile Created`
* `Salon Head Id`
* `Salon Head Name`
* `Scheme`
* `Salon Id`
* `Salon Name`
* `Salon Location`
* `Salon City`
* `Is Salon Checked`
* `Is Salon Trained`
* `Is Request Invoice`
* `Is Payment Route Set`
* `Status`
* `Source`
* `Created Date`
* `Status Updated At`
* `Days`

### E. Category: `offers`

#### 1. Report Type: `offers_list` (Salon Offers List)
* `salon_id`
* `1st_discount`
* `1st_cashback`
* `weekday_discount`
* `weekday_cashback`
* `weekend_discount`
* `weekend_cashback`
* `Head Name`
* `Partner Name`
* `Partner Location`
* `Partner City`
* `Pincode`
* `Area`
* `Margin`
* `Is Enabled`
* `Offer Type`
* `Last 30 Days Payment Count`
* `Last 30 Days Billing`
* `Last Month Completion Rate`
* `Last Month Appointment Count`
* `Current Balance`
* `No. of Outlets in Head`
* `Last 30 Days PnL`
* `Growth Manager`
* `Last Updated At`

### F. Category: `giftcards`

#### 1. Report Type: `transactions_list` (Gift Card Transactions list)
* `Purchasing Customer`
* `Purchasing Customer Contact`
* `Gender`
* `Amount`
* `Claiming Customer`
* `Claiming Customer Contact`
* `Purchased At`
* `Status`
* `Claimed At`

---

## 4. How to Add a New Report / Exporter

To integrate a new report into the report service, follow these four steps:

### Step 1: Add Headers to Column Configurations
Open [core/columns.py](file:///C:/Users/luzot/Herd/python-report-service/core/columns.py) and define the headers list and any optional join check helper functions:

```python
MY_CUSTOM_HEADERS = [
    "Id",
    "Name",
    "Created At"
]

def my_custom_needs_join(selected_columns: Optional[List[str]]) -> bool:
    # Optional logic to check if selectedColumns contains fields from joined tables
    ...
```

### Step 2: Create the Exporter Class
Create a new file in the `exporters/` directory (e.g., `exporters/my_custom_report.py`) inheriting from `BaseExporter`. Import the headers from `core.columns`:

```python
import gc
from datetime import datetime
from sqlalchemy import text
from db import AsyncSessionLocal
from core.base import BaseExporter
from core.columns import MY_CUSTOM_HEADERS

class MyCustomExporter(BaseExporter):
    @classmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        # 1. Parse selected columns from payload
        selected_columns = kwargs.get("payload", {}).get("selectedColumns")
        
        # 2. Build query
        query = text("""
            SELECT id, name, created_at FROM my_table 
            WHERE (:start_date IS NULL OR created_at >= :start_date)
              AND (:end_date IS NULL OR created_at <= :end_date)
        """)

        async with AsyncSessionLocal() as session:
            conn = await session.connection()
            result_stream = await conn.stream(
                query,
                {
                    "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
                    "end_date": end_date.strftime("%Y-%m-%d") if end_date else None
                }
            )

            # Get the wrapped writer (handles dynamic column filtering automatically)
            headers = MY_CUSTOM_HEADERS
            writer = cls.get_csv_writer(output_file, headers, **kwargs)
            writer.writerow(headers)

            gc.disable()
            try:
                processed_count = 0
                async for partition in result_stream.partitions(1000):
                    rows_to_write = [
                        [
                            row.id,
                            row.name,
                            row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
                        ]
                        for row in partition
                    ]
                    writer.writerows(rows_to_write)
                    processed_count += len(partition)
                    if progress_callback:
                        await progress_callback(processed_count)
            finally:
                gc.enable()
```

### Step 3: Register the Exporter
Import and register your class inside `core/registry.py`:

```python
from exporters.my_custom_report import MyCustomExporter

CATEGORY_REGISTRY: Dict[str, Dict[str, Type[BaseExporter]]] = {
    "appointments": {
        "summary": AppointmentSummaryExporter,
        "salon_wise": SalonWiseAppointmentsExporter,
        "all_list": AllAppointmentsExporter,
        "completion_rate": CompletionRateExporter,
    },
    "salon_heads": {
        "passbook": SalonHeadPassbookExporter,
    },
    "my_new_category": {
        "custom_report_name": MyCustomExporter,
    }
}
```

### Step 3: Call the Export API
Trigger the new report via the export endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: <token>" \
  -d '{
    "category": "my_new_category",
    "reports": ["custom_report_name"],
    "email": "luzotech@luzo.app"
  }'
```

---

## 5. Code Standards & Performance Guidelines

When modifying or adding exporters, new developers **must** adhere to the following design standards to ensure high performance and event loop stability.

### A. Dynamic Query Guidelines
1. **Omit Joins Dynamically**: Do not perform static SQL joins to table entities if they are not requested in `selectedColumns` (e.g. skip joining the `customers` table if no customer data is selected). Define these checking helpers in `core/columns.py` to keep exporter files clean.
2. **Correlated Subqueries**: Aggregation subqueries (like cancellation breakdowns in `salon_wise_appointments.py`) should be wrapped in conditional checks so that they are omitted when cancellation metrics are not requested, preventing unnecessary database table scans.
3. **Covering Indexes for Heavy Aggregations**: For large tables (like `salon_head_passbooks` with 3.4M+ rows), heavy aggregates (like PnL sum queries) should use a composite covering index (e.g., `idx_shp_deleted_txn_salon_pnl` on `(deleted_at, txn_date, salon_id, pnl)`) so that the database can satisfy the query entirely from the index without reading raw rows from disk. This reduces execution times from 120+ seconds to under 1 second.

### B. Tight Loop & Memory Management
1. **Garbage Collection (GC) Control**: Temporarily disable garbage collection (`gc.disable()`) inside tight streaming partitions writing loops, and re-enable it (`gc.enable()`) inside a `finally` block to prevent Python CPU overhead.
2. **Chunking/Partitioning**: Always stream and write records in bulk partitions (e.g., `1000` rows) rather than loading entire datasets into memory.
3. **Safe Property Access**: Always fetch database row attributes using `getattr(row, "field_name", default_value)` to support dynamic query projection safely.

### C. Database Connection Lifecycle
1. **Windows Event Loop Safety**: Explicitly call `await dispose_loop_engine()` inside the worker task `finally` block to prevent connection leaks across Celery task event loops on Windows.
2. **Async Operations**: All database interaction must be async using SQLAlchemy and `aiomysql`.

### D. File I/O & Cloud Storage
1. **Bypass Local Disk**: Never write export files to local disks. All CSV files and ZIP files must utilize in-memory buffers (`io.StringIO` and `io.BytesIO`).
2. **CDN Streaming**: Upload files directly from RAM using `s3_client.upload_fileobj` to leverage direct memory-to-cloud streaming.

---

## 6. Database Connection Configurations ([db.py](file:///C:/Users/luzot/Herd/python-report-service/db.py))

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Uses aiomysql for asynchronous connection
DATABASE_URL = f"mysql+aiomysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
```
The database connection pool details and settings are defined in [config.py](file:///C:/Users/luzot/Herd/python-report-service/config.py) and initialized asynchronously inside [db.py](file:///C:/Users/luzot/Herd/python-report-service/db.py).
