"""
API клиент для взаимодействия с FastAPI сервисом генерации
"""
import httpx
import asyncio
import os
import sys
from typing import Optional, Dict, Any
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logger = logging.getLogger(__name__)

# Импортируем конфигурацию из config.py
from config.config import USER, PASSWORD, API_HOST, API_PORT

# URL FastAPI сервиса
FASTAPI_BASE_URL = f"http://{API_HOST}:{API_PORT}"


class GenerationAPIClient:
    """Клиент для работы с API генерации фото и видео"""
    
    def __init__(self, base_url: str = FASTAPI_BASE_URL):
        self.base_url = base_url
        self.timeout = httpx.Timeout(300.0)  # 5 минут для долгих запросов
    
    async def generate_photo(
        self, 
        uin: str, 
        photos: list[str],
        item_type: Optional[str] = None,
        gender: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Запуск генерации фото изделия на человеке
        
        Args:
            uin: УИН изделия (используется как id_client)
            photos: Список URL фотографий из РМП
            item_type: Тип изделия (например, "Кольцо с синтетическим камнем Золото")
            gender: Гендер изделия (Мужской/Женский)
        
        Returns:
            dict с photo_url и данными или None при ошибке
        """
        url = f"{self.base_url}/GeneratePhoto"
        
        payload = {
            "id_client": uin,
            "photos": photos
        }
        
        # Добавляем тип изделия, если передан
        if item_type:
            payload["item_type"] = item_type
        
        # Добавляем гендер, если передан
        if gender:
            payload["gender"] = gender
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                # Извлекаем URL из структуры {data: {generated_photo_url: ...}}
                photo_url = result.get('data', {}).get('generated_photo_url')
                logger.info(f"[API] Фото сгенерировано для УИН {uin}: {photo_url}")
                
                # Возвращаем упрощенную структуру для бота
                return {
                    'photo_url': photo_url,
                    'id_client': result.get('id_client'),
                    'error': result.get('error')
                }
                
        except httpx.HTTPError as e:
            logger.error(f"[API] Ошибка при генерации фото: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] Неожиданная ошибка при генерации фото: {e}")
            return None
    
    @staticmethod
    async def download_photo(photo_url: str) -> Optional[bytes]:
        """
        Скачивание фото с РМП сервера с авторизацией
        
        Args:
            photo_url: URL фото на РМП сервере
        
        Returns:
            bytes фото или None при ошибке
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    photo_url,
                    auth=(USER, PASSWORD) if USER else None
                )
                response.raise_for_status()
                logger.info(f"[API] Фото скачано с {photo_url}, размер: {len(response.content)} байт")
                return response.content
                
        except httpx.HTTPError as e:
            logger.error(f"[API] Ошибка при скачивании фото {photo_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] Неожиданная ошибка при скачивании фото: {e}")
            return None
    
    async def download_photos_parallel(self, photo_urls: list[str]) -> list[Optional[bytes]]:
        """
        Параллельное скачивание нескольких фото с РМП сервера
        
        Args:
            photo_urls: Список URL фото на РМП сервере
        
        Returns:
            Список bytes фото (или None для неудачных загрузок)
        """
        logger.info(f"[API] Начало параллельной загрузки {len(photo_urls)} фото")
        tasks = [self.download_photo(url) for url in photo_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обработка исключений
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[API] Ошибка при загрузке фото #{i}: {result}")
                processed_results.append(None)
            else:
                processed_results.append(result)
        
        successful = sum(1 for r in processed_results if r is not None)
        logger.info(f"[API] Загружено {successful} из {len(photo_urls)} фото")
        return processed_results
    
    @staticmethod
    async def download_video(video_url: str) -> Optional[bytes]:
        """
        Скачивание видео с РМП сервера с авторизацией
        
        Args:
            video_url: URL видео на РМП сервере
        
        Returns:
            bytes видео или None при ошибке
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    video_url,
                    auth=(USER, PASSWORD) if USER else None
                )
                response.raise_for_status()
                logger.info(f"[API] Видео скачано с {video_url}, размер: {len(response.content)} байт")
                return response.content
                
        except httpx.HTTPError as e:
            logger.error(f"[API] Ошибка при скачивании видео {video_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] Неожиданная ошибка при скачивании видео: {e}")
            return None
    
    async def generate_video(
        self, 
        uin: str
    ) -> Optional[Dict[str, Any]]:
        """
        Запуск генерации видео из уже сгенерированного фото
        
        Требования:
        - Фото УЖЕ должно быть сгенерировано через generate_photo()
        - URL фото: https://media.example.com/{УИН}_10.jpg
        
        Args:
            uin: УИН изделия
        
        Returns:
            dict с task_id и статусом или None при ошибке
        """
        url = f"{self.base_url}/GenerateVideo"
        
        payload = {
            "id_client": uin,
            "photos": []
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"[API] Генерация видео запущена для УИН {uin}, task_id: {result.get('task_id')}")
                return result
                
        except httpx.HTTPError as e:
            logger.error(f"[API] Ошибка при запуске генерации видео: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] Неожиданная ошибка при генерации видео: {e}")
            return None
    
    async def check_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Проверка статуса генерации
        
        Args:
            task_id: ID задачи
        
        Returns:
            dict со статусом и результатами или None при ошибке
        """
        url = f"{self.base_url}/VideoStatus/{task_id}"
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                result = response.json()
                
                return result
                
        except httpx.HTTPError as e:
            logger.error(f"[API] Ошибка при проверке статуса {task_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] Неожиданная ошибка при проверке статуса: {e}")
            return None
    
    async def wait_for_completion(
        self, 
        task_id: str, 
        max_wait_seconds: int = 300,
        initial_delay: int = 60,
        poll_interval: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Ожидание завершения генерации с polling
        
        Args:
            task_id: ID задачи
            max_wait_seconds: Максимальное время ожидания (секунды)
            initial_delay: Начальная задержка перед первой проверкой (секунды, по умолчанию 60)
            poll_interval: Интервал последующих проверок (секунды, по умолчанию 10)
        
        Returns:
            dict с результатами или None при ошибке/таймауте
        """
        # Начальная задержка перед первой проверкой
        logger.info(f"[API] Ожидание {initial_delay}с перед первой проверкой статуса {task_id}")
        await asyncio.sleep(initial_delay)
        elapsed = initial_delay
        
        while elapsed < max_wait_seconds:
            status_data = await self.check_status(task_id)
            
            if not status_data:
                return None
            
            status = status_data.get("status")
            
            if status == "SUCCEEDED":
                logger.info(f"[API] Генерация завершена успешно: {task_id}")
                return status_data
            
            elif status == "FAILED":
                logger.error(f"[API] Генерация провалилась: {task_id}")
                return status_data
            
            elif status in ["PROCESSING", "PENDING"]:
                logger.debug(f"[API] Генерация в процессе: {task_id}, прошло {elapsed}с")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
            
            else:
                logger.warning(f"[API] Неизвестный статус {status} для {task_id}")
                return status_data
        
        logger.warning(f"[API] Таймаут ожидания для {task_id} ({max_wait_seconds}с)")
        return None


# Глобальный экземпляр клиента
api_client = GenerationAPIClient()
