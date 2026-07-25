from typing import Dict, Any
from enum import IntEnum


class ErrorStatus(IntEnum):
    """Коды ошибок"""
    SUCCESS = 0
    NO_DATA = 1
    GENERATION_ERROR = 2
    SERVER_ERROR = 99


def create_error_response(
    client_id: str,
    error_status: ErrorStatus,
    error_message: str
) -> Dict[str, Any]:
    """Создает унифицированный ответ об ошибке"""
    
    return {
        "id_client": client_id,
        "data": {},
        "error": {
            "status": int(error_status),
            "detail": error_message
        }
    }