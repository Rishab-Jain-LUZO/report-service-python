# Luzo Universal Report Service

The **Luzo Universal Report Service** is a high-performance Python microservice designed to compile and export massive datasets (such as Salon Head Passbook transactions, Leads, and Appointments) asynchronously. By shifting heavy querying and export compilation away from the core PHP application, it avoids database locks, high memory usage, and local disk write overhead.

---

## 🚀 Key Features

* **Asynchronous Execution**: Leverages **Celery** and **Redis** to run export jobs in the background, keeping the main HTTP response times sub-millisecond.
* **In-Memory Streaming**: Bypasses local disk I/O bottlenecks by compiling CSV sheets and compressing them into ZIP archives entirely in-memory using `io.StringIO` and `io.BytesIO`.
* **Direct Cloud Streaming**: Uploads finalized report archives directly from RAM to AWS S3 using direct multipart upload, avoiding temp file writing.
* **Dynamic Column Selection**: Supports client-side filtering via `selectedColumns`. The service dynamically projects SQL queries to only load requested columns.
* **SQL Join Pruning**: Automatically omits SQL table joins (like joining the heavy `customers` table) unless customer-specific columns are requested, drastically reducing database load.
* **Covering Index Utilization**: Engineered to leverage composite indexes (e.g. `idx_shp_deleted_txn_salon_pnl` on `salon_head_passbooks`) to satisfy complex aggregations directly from DB memory.
* **SMTP Notifications**: Automatically dispatches rich email notifications containing secure, pre-signed S3 download links upon completion.

---

## 🛠️ Technology Stack

* **API Layer**: FastAPI (ASGI)
* **Task Queue**: Celery
* **Message Broker / Backend**: Redis
* **Database Access**: SQLAlchemy (async connection pool utilizing `aiomysql`)
* **Object Storage**: AWS S3 (via Boto3)
* **Mailing Service**: SMTP (secure TLS/SSL)

---

## 📦 Getting Started

### 1. Prerequisites
Ensure you have the following installed on your machine:
* Python 3.10+
* Redis Server (default port `6379`)
* MySQL Database (compatible schema structure)

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone <repository-url>
cd python-report-service
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```ini
# App Configuration
PORT=8000
REPORT_SERVICE_TOKEN=your_secure_auth_token

# Redis Configuration
REDIS_URL=redis://127.0.0.1:6379/0

# Database Configuration
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_db_password
DB_NAME=luzo_database

# S3 Configuration
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=ap-south-1
AWS_BUCKET=your_s3_bucket

# SMTP Configuration
MAIL_HOST=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_app_password
MAIL_FROM_ADDRESS=no-reply@luzo.app
MAIL_FROM_NAME="Luzo Reports"
```

### 4. Running the Application

#### Option A: Local Manual Run
* **Start the FastAPI Dev Server**:
  ```bash
  uvicorn main:app --host 127.0.0.1 --port 8000 --reload
  ```

* **Start the Celery Worker**:
  * **On Windows (with Thread Pool)**:
    ```bash
    celery -A tasks.celery_app worker --loglevel=info -P threads
    ```
  * **On Linux / Production**:
    ```bash
    celery -A tasks.celery_app worker --loglevel=info
    ```

#### Option B: Docker Containers (Recommended & Simplest Setup)
Using Docker is recommended as it packages Python, Redis, and all library packages automatically without needing individual system installs.

1. Ensure **Docker Desktop** is running.
2. Execute the following command in the repository root:
   ```bash
   docker-compose up --build
   ```

*This will automatically pull Redis, build the FastAPI app container, install requirements, and run both the API server and the Celery worker in parallel.*

---

## 📡 API Reference

All requests to the export endpoints must include the security token header:
`X-Report-Service-Token: <your_secure_auth_token>`

### 1. Trigger Export Job
Asynchronously compiles CSV reports into a ZIP archive.

* **URL**: `/api/v1/export`
* **Method**: `POST`
* **Headers**:
  * `Content-Type: application/json`
  * `X-Report-Service-Token: <token>`

#### Payload Options:
* `category` (String, Required): Logical category (e.g., `appointments`, `salon_heads`, `regional_managers`, `leads`, `offers`, `giftcards`).
* `reports` (Array of Strings, Required): The specific sub-reports to compile.
* `email` (String, Required): Destination email for the download link.
* `startDate`/`endDate` (String, Optional): Date filter limits (YYYY-MM-DD).
* `selectedColumns` (Array of Strings, Optional): Case-insensitive list of specific columns to output.

#### Example: Gift Cards Export
```bash
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -H "X-Report-Service-Token: your_token" \
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

---

### 2. Check Task Status
Retrieve the progress, state, or error messages of a Celery background job.

* **URL**: `/api/v1/export/status/{task_id}`
* **Method**: `GET`

#### Example Status Response:
```json
{
  "status": "in_progress",
  "progress": 45,
  "message": "Generating: passbook: 12,500 rows"
}
```

---

## 📂 Export Categories Catalog

| Category | Available Reports | Filters / Parameters Supported |
| :--- | :--- | :--- |
| **`appointments`** | `summary`, `salon_wise`, `all_list`, `completion_rate` | `startDate`, `endDate`, `selectedColumns` |
| **`salon_heads`** | `passbook` | `startDate`, `endDate`, `salonHeadIds`, `salonHeadWalletIds`, `selectedColumns` |
| **`regional_managers`** | `partner_rm_list`, `notes_list`, `completion_rate` | `startDate`, `endDate`, `status`, `monthLimit`, `weekLimit`, `selectedColumns` |
| **`leads`** | `leads_list` | `startDate`, `endDate`, `status`, `selectedColumns` |
| **`offers`** | `offers_list` | `offerType`, `filters` (`is_active`, `is_deleted`, `searchTerm`) |
| **`giftcards`** | `transactions_list` | `startDate`, `endDate`, `status` (`CLAIMED`/`UNCLAIMED`), `searchTerm` |

---

## 🛠️ Adding a New Exporter (Developer Guide)

1. **Define Headers**: Add the report headers list in `core/columns.py`. Implement optional helper checking routines to optimize database queries based on the requested columns (e.g. `needs_user_join(selected_columns)`).
2. **Create Exporter Class**: Inherit `BaseExporter` in `exporters/` directory (e.g., `exporters/custom_exporter.py`). Implement the `async def generate(...)` method. Ensure to disable GC inside writing loops (`gc.disable()`) and stream partitions (`partitions(1000)`).
3. **Register Exporter**: Map the new class to a report name in `core/registry.py` under your category key.
4. **Call the Endpoint**: Deploy and request your new category/report name via `/api/v1/export`.
