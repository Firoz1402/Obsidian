import structlog
from supabase import Client, create_client

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SupabaseClientProxy:
    client: Client | None = None

    def init_client(self) -> None:
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        else:
            logger.warning("supabase_configuration_missing")


supabase_proxy = SupabaseClientProxy()
