from typing import Any, Optional


def success_response(data: Any = None, message: str = "Success") -> dict:
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error_response(
    code: str,
    message: str,
    details: Optional[Any] = None,
    request_id: Optional[str] = None,
) -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        },
    }
