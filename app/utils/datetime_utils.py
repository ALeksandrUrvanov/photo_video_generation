from datetime import datetime

def get_timestamp() -> str:
    """Получение временной метки в читаемом формате"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S") 