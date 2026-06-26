import json
import structlog

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from app.config.settings import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class FirebaseProxy:
    app: firebase_admin.App | None = None

    def init_client(self) -> None:
        if firebase_admin._apps:
            self.app = firebase_admin.get_app()
            return

        if not settings.FIREBASE_CREDENTIALS_JSON:
            logger.warning("firebase_credentials_missing")
            return

        cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
        self.app = firebase_admin.initialize_app(credentials.Certificate(cred_dict))
        logger.info(
            "firebase_initialized",
            extra={"project_id": cred_dict.get("project_id")},
        )

    def verify_id_token(self, id_token: str) -> dict:
        if not self.app:
            raise RuntimeError("Firebase is not initialized")
        return firebase_auth.verify_id_token(id_token, app=self.app)


firebase_proxy = FirebaseProxy()
