import csv
from abc import ABC, abstractmethod
from datetime import datetime

class FilteredCSVWriter:
    def __init__(self, target_writer, original_headers, selected_columns):
        self.target_writer = target_writer
        self.original_headers = original_headers
        
        # Build mapping (case-insensitive and whitespace stripped)
        header_map = {h.lower().strip(): idx for idx, h in enumerate(original_headers)}
        
        self.indices = []
        self.filtered_headers = []
        for col in selected_columns:
            col_key = col.lower().strip()
            if col_key in header_map:
                idx = header_map[col_key]
                self.indices.append(idx)
                self.filtered_headers.append(original_headers[idx])
        
        # If no selected columns match, fallback to original headers
        if not self.indices:
            self.indices = list(range(len(original_headers)))
            self.filtered_headers = original_headers
            
        self.headers_written = False

    def writerow(self, row):
        if not self.headers_written:
            self.target_writer.writerow(self.filtered_headers)
            self.headers_written = True
            # If the exporter's first writerow call is passing the full original headers,
            # we skip writing it again since we already wrote the filtered headers.
            if len(row) == len(self.original_headers):
                return
        
        # Filter the row data
        try:
            filtered_row = [row[idx] for idx in self.indices]
            self.target_writer.writerow(filtered_row)
        except IndexError:
            # Fallback if row length is unexpected
            self.target_writer.writerow(row)

    def writerows(self, rows):
        if not self.headers_written:
            self.target_writer.writerow(self.filtered_headers)
            self.headers_written = True
            
        filtered_rows = []
        for row in rows:
            # If the row matches original headers, skip it
            if len(row) == len(self.original_headers) and all(r == h for r, h in zip(row, self.original_headers)):
                continue
            try:
                filtered_rows.append([row[idx] for idx in self.indices])
            except IndexError:
                filtered_rows.append(row)
        self.target_writer.writerows(filtered_rows)


class BaseExporter(ABC):
    @classmethod
    @abstractmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        """
        Generates a report file and returns the output file path.
        Every new report class must implement this method.
        """
        pass

    @classmethod
    def get_csv_writer(cls, output_file, headers, **kwargs):
        payload = kwargs.get("payload", {}) or kwargs
        selected_columns = payload.get("selectedColumns")
        raw_writer = csv.writer(output_file)
        if selected_columns:
            return FilteredCSVWriter(raw_writer, headers, selected_columns)
        return raw_writer
