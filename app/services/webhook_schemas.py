from pydantic import BaseModel, Field
from typing import List, Optional


class ErrorInfo(BaseModel):
    """Информация об ошибке"""
    status: int = Field(..., description="Код ошибки: 0=Успех, 1=Нет данных, 2=Ошибка генерации фото, 99=Прочая ошибка")
    detail: str = Field(..., description="Описание ошибки")


class PhotoGenerationRequest(BaseModel):
    """Схема запроса генерации фото"""
    id_client: str = Field(..., description="Уникальный идентификатор клиента")
    photos: List[str] = Field(..., description="Список имен файлов фотографий (минимум 1)")
    item_type: Optional[str] = Field(None, description="Тип изделия (например, 'Кольцо с синтетическим камнем Золото')")
    gender: Optional[str] = Field(None, description="Гендер изделия (Мужской/Женский)")


class PhotoGenerationData(BaseModel):
    """Данные сгенерированного фото"""
    generated_photo_url: str = Field("", description="URL сгенерированного фото")
    generated_photo_name: str = Field("", description="Имя сгенерированного файла")


class PhotoGenerationResponse(BaseModel):
    """Схема ответа генерации фото"""
    id_client: str = Field(..., description="Уникальный идентификатор клиента")
    data: PhotoGenerationData = Field(default_factory=PhotoGenerationData, description="Данные сгенерированного фото")
    error: ErrorInfo = Field(..., description="Информация об ошибке")


class VideoGenerationRequest(BaseModel):
    """Схема запроса генерации видео"""
    id_client: str = Field(..., description="Уникальный идентификатор клиента")
    photos: List[str] = Field(..., description="Список имен файлов фотографий (минимум 1)")


class VideoGenerationInitResponse(BaseModel):
    """Схема ответа при создании задачи генерации видео"""
    task_id: str = Field(..., description="ID задачи для проверки статуса")
    status: str = Field("PROCESSING", description="Статус задачи")
    message: str = Field("Задача создана, генерация началась", description="Сообщение")
    estimated_completion_time: int = Field(300, description="Ориентировочное время завершения в секундах")
    recommended_polling_delay: int = Field(60, description="Рекомендуемая задержка перед первым polling (секунды)")


class VideoGenerationData(BaseModel):
    """Данные сгенерированного фото и видео"""
    photo_url: str = Field("", description="URL сгенерированного фото")
    video_url: Optional[str] = Field(None, description="URL сгенерированного видео (если успешно)")


class VideoStatusResponse(BaseModel):
    """Схема ответа статуса задачи видео"""
    task_id: str = Field(..., description="ID задачи")
    status: str = Field(..., description="Статус: PROCESSING, SUCCEEDED, FAILED")
    data: VideoGenerationData = Field(default_factory=VideoGenerationData, description="Данные фото и видео")
    error: ErrorInfo = Field(..., description="Информация об ошибке")