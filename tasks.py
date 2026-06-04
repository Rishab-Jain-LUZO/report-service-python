import os
import shutil
import zipfile
import asyncio
import smtplib
import boto3
import io
from datetime import datetime
from uuid import uuid4
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from celery import Celery
from config import settings

# Import Exporter Registry
from core.registry import CATEGORY_REGISTRY

def safe_remove_directory(path: str, retries: int = 5, delay: float = 0.5):
    import time
    for i in range(retries):
        try:
            if os.path.exists(path):
                shutil.rmtree(path)
            return
        except PermissionError:
            if i < retries - 1:
                time.sleep(delay)
            else:
                print(f"Warning: Cleanup failed for directory {path} due to file lock. Skipping deletion.")
        except Exception as e:
            print(f"Warning: Failed to delete directory {path}: {str(e)}")
            return

# Setup Celery application client
celery_app = Celery("report_tasks", broker=settings.redis_url, backend=settings.redis_url)

def upload_fileobj_to_s3(file_obj, s3_key: str) -> str:
    # Setup AWS S3 Client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region
    )
    # Uploading the file-like object directly to S3
    s3_client.upload_fileobj(file_obj, settings.s3_bucket_name, s3_key)
    # Returning the public CDN URL as configured in the env variables
    return f"https://cdn.luzo.app/{s3_key}"

def send_download_email(recipient_email: str, category_name: str, download_url: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Admin {category_name.capitalize()} Report"
    msg["From"] = f"LUZO <{settings.smtp_from_email}>"
    msg["To"] = recipient_email

    # Formulating HTML mail body payload
    html_content = f"""
    <p>Your Admin {category_name.capitalize()} Report is ready.</p>
    <p>
        <a href='{download_url}'>
            Download Report
        </a>
    </p>
    <p>
        <strong>Note:</strong>
        This file will be automatically deleted after 3 days.
    </p>
    """
    msg.attach(MIMEText(html_content, "html"))

    # Sending email using standard SMTP server
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, recipient_email, msg.as_string())

@celery_app.task(bind=True, name="tasks.generic_export")
def generic_export_task(self, payload: dict):
    category = payload["category"]
    reports = payload["reports"]
    email = payload["email"]
    start_date_str = payload.get("startDate")
    end_date_str = payload.get("endDate")
    
    # Establish dates parameters boundaries
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d") if end_date_str else datetime.utcnow()
    if not start_date_str:
        from datetime import timedelta
        start_date = end_date - timedelta(days=180)
    else:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")

    # Update initial status
    self.update_state(state='PROGRESS', meta={'progress': 5, 'status': 'Initializing in-memory workspace streams...'})

    generated_csv_buffers = {}
    
    try:
        # Retrieve the exporter registry for this category
        category_registry = CATEGORY_REGISTRY[category]
        
        # Define an async helper to run all exporters concurrently in a single event loop
        # and dispose of connection pool before closing the event loop
        async def run_exporters():
            progress_data = {}
            
            async def run_exporter(r_type):
                if r_type not in category_registry:
                    return
                exporter_cls = category_registry[r_type]
                
                # Use in-memory StringIO buffer to bypass disk I/O bottlenecks
                csv_buffer = io.StringIO()
                progress_data[r_type] = "Starting..."
                
                
                # Progress callback to capture and combine rows processed concurrently
                async def progress_callback(rows_processed):
                    progress_data[r_type] = f"{rows_processed:,} rows"
                    status_str = " | ".join([f"{k}: {v}" for k, v in progress_data.items()])
                    self.update_state(
                        state='PROGRESS',
                        meta={
                            'progress': 10 + int((len(generated_csv_buffers) / len(reports)) * 75),
                            'status': f"Generating: {status_str}"
                        }
                    )
                
                await exporter_cls.generate(
                    csv_buffer, 
                    start_date, 
                    end_date, 
                    progress_callback=progress_callback,
                    payload=payload
                )
                generated_csv_buffers[r_type] = csv_buffer
                progress_data[r_type] = "Finished"
                status_str = " | ".join([f"{k}: {v}" for k, v in progress_data.items()])
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'progress': 10 + int((len(generated_csv_buffers) / len(reports)) * 75),
                        'status': f"Generating: {status_str}"
                    }
                )

            # Create tasks to run concurrently using asyncio.gather
            tasks = [run_exporter(r_type) for r_type in reports]
            await asyncio.gather(*tasks)
            
            # Dispose of the engine connection pool for this specific event loop to prevent connection leaks
            # and proactor/selector errors across subsequent event loops on Windows
            from db import dispose_loop_engine
            await dispose_loop_engine()
            
        # Run the async helper
        asyncio.run(run_exporters())
        
        # Creating ZIP archive in memory to eliminate local disk write operations
        self.update_state(state='PROGRESS', meta={'progress': 90, 'status': 'Compiling in-memory reports into a ZIP archive...'})
        zip_filename = f"{category.capitalize()}_Report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for r_type, csv_buf in generated_csv_buffers.items():
                zip_file.writestr(f"{r_type}.csv", csv_buf.getvalue())
        
        # Reset byte buffer position to start of stream before upload
        zip_buffer.seek(0)
                
        # Upload finished ZIP archive directly to Amazon S3 as file-like stream
        self.update_state(state='PROGRESS', meta={'progress': 95, 'status': 'Uploading in-memory ZIP archive to S3 cloud storage...'})
        s3_key = f"exports/{category}-reports/{datetime.utcnow().strftime('%Y/%m')}/{zip_filename}"
        download_url = upload_fileobj_to_s3(zip_buffer, s3_key)
        
        # Send Email notification with secure link
        self.update_state(state='PROGRESS', meta={'progress': 98, 'status': 'Sending download link via SMTP email notification...'})
        send_download_email(email, category, download_url)
        print(f"Export completed: {download_url}")
        
    except Exception as e:
        print(f"Background task failed with exception: {str(e)}")
        raise e
        
    finally:
        # Close in-memory buffers to free up RAM resources
        for csv_buf in generated_csv_buffers.values():
            csv_buf.close()
