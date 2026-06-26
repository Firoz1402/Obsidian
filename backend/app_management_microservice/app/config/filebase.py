import boto3
from botocore.config import Config

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class FilebaseClientProxy:
    client = None

    def init_client(self) -> None:
        if not (settings.FILEBASE_ACCESS_KEY_ID and settings.FILEBASE_SECRET_ACCESS_KEY):
            logger.warning("filebase_configuration_missing")
            return

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.FILEBASE_ENDPOINT,
            aws_access_key_id=settings.FILEBASE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.FILEBASE_SECRET_ACCESS_KEY,
            region_name=settings.FILEBASE_REGION,
            config=Config(signature_version="s3v4"),
        )


filebase_proxy = FilebaseClientProxy()
