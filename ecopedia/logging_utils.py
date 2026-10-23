import logging
import os


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        message = super().format(record)
        for name in ('OPENAI_API_KEY', 'GMS_KEY', 'LANGSMITH_API_KEY'):
            secret = os.getenv(name, '')
            if secret:
                message = message.replace(secret, '[REDACTED]')
        return message


def configure_logging(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    resolved = str(path.resolve())
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == resolved for h in root.handlers):
        handler = logging.FileHandler(path, encoding='utf-8')
        handler.setLevel(logging.WARNING)
        handler.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(message)s'))
        root.addHandler(handler)
    root.setLevel(logging.WARNING)
