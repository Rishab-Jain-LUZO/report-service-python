from abc import ABC, abstractmethod
from datetime import datetime

class BaseExporter(ABC):
    @classmethod
    @abstractmethod
    async def generate(cls, output_file, start_date: datetime, end_date: datetime, progress_callback=None, **kwargs) -> None:
        """
        Generates a report file and returns the output file path.
        Every new report class must implement this method.
        """
        pass
