import base64
import asyncio
from io import BytesIO
from typing import Optional
from http import HTTPStatus
from PIL import Image

import dashscope
from dashscope import VideoSynthesis

from app.utils.logger import get_logger
from app.utils.datetime_utils import get_timestamp
from config.config import ALIBABA_WAN_CONFIG

logger = get_logger(__name__)


class VideoGenerationService:
    """Сервис генерации видео через Alibaba DashScope SDK"""
    
    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        resolution: str | None = None,
        max_polling_time: int | None = None,
        max_image_size: int | None = None,
    ):
        self.api_key = api_key
        self.model = model or ALIBABA_WAN_CONFIG.get("model")
        self.resolution = resolution or ALIBABA_WAN_CONFIG.get("resolution")
        self.max_polling_time = max_polling_time or ALIBABA_WAN_CONFIG.get("max_polling_time")
        self.max_image_size = max_image_size or ALIBABA_WAN_CONFIG.get("max_image_size")
        
        # Настройка SDK base URL
        if base_url or ALIBABA_WAN_CONFIG.get("base_url"):
            url = base_url or ALIBABA_WAN_CONFIG.get("base_url")
            # Извлекаем base URL без пути
            if "dashscope-intl.aliyuncs.com" in url:
                dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
            else:
                dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
        
        logger.info(f"[{get_timestamp()}] VideoGenerationService (Wan2.2-i2v-Plus) инициализирован")
    
    def encode_image_to_base64(self, image_data: bytes) -> str:
        """
        Кодирует изображение в base64 формат
        Оптимизирует размер перед отправкой
        """
        input_buf = BytesIO(image_data)
        try:
            with Image.open(input_buf) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    processed_im = im.convert("RGBA")
                else:
                    processed_im = im.convert("RGB")
                
                w, h = im.size
                long_side = max(w, h)
                
                # Уменьшаем если больше max_image_size
                if long_side > self.max_image_size:
                    scale = self.max_image_size / float(long_side)
                    new_w, new_h = int(w * scale), int(h * scale)
                    processed_im = processed_im.resize((new_w, new_h), Image.LANCZOS)
                
                output_buf = BytesIO()
                try:
                    # JPEG с качеством 85 для оптимального размера
                    processed_im.save(output_buf, format="JPEG", quality=85, optimize=True)
                    output_buf.seek(0)
                    encoded = base64.b64encode(output_buf.read()).decode('utf-8')
                    return f"data:image/jpeg;base64,{encoded}"
                finally:
                    output_buf.close()
                    if processed_im is not im:
                        processed_im.close()
        finally:
            input_buf.close()
    
    async def create_video_task(
        self, 
        image_data: bytes, 
        prompt: str
    ) -> tuple[str, str, any]:
        """
        Создает задачу генерации видео через DashScope SDK
        
        Args:
            image_data: Байты изображения
            prompt: Промпт для видео
            
        Returns:
            (task_id, task_status, response_object)
        """
        # Кодируем изображение
        img_base64 = self.encode_image_to_base64(image_data)
        
        try:
            # Асинхронный вызов через SDK
            def _call_sdk():
                return VideoSynthesis.async_call(
                    api_key=self.api_key,
                    model=self.model,
                    prompt=prompt,
                    img_url=img_base64,
                    resolution=self.resolution,
                    duration=5,  # 5 секунд для wan2.2
                    prompt_extend=False,  # не расширяем промпт (у нас уже от Claude)
                    watermark=False,  # без водяного знака
                    negative_prompt=""
                )
            
            # Запускаем в thread pool
            response = await asyncio.to_thread(_call_sdk)
            
            if response.status_code == HTTPStatus.OK:
                task_id = response.output.task_id
                task_status = response.output.task_status
                logger.info(f"Alibaba задача: {task_id}")
                # Возвращаем также response объект для SDK wait()
                return task_id, task_status, response
            else:
                error_msg = f"Status: {response.status_code}, Code: {response.code}, Message: {response.message}"
                logger.error(f"[{get_timestamp()}] Ошибка создания задачи: {error_msg}")
                raise RuntimeError(f"Ошибка Alibaba API: {error_msg}")
                
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Ошибка создания задачи видео: {e}")
            raise RuntimeError(f"Ошибка создания задачи: {str(e)}")
    
    async def wait_for_video(self, task_response: any) -> Optional[str]:
        """
        Ожидает завершения генерации видео через SDK wait()
        
        Args:
            task_response: Response объект от create_video_task
            
        Returns:
            video_url если успешно, None если ошибка
        """
        task_id = task_response.output.task_id
        
        try:
            # SDK wait() с таймаутом
            def _wait_sdk():
                return VideoSynthesis.wait(
                    task=task_response,
                    api_key=self.api_key
                )
            
            # Запускаем с таймаутом
            response = await asyncio.wait_for(
                asyncio.to_thread(_wait_sdk),
                timeout=self.max_polling_time
            )
            
            if response.status_code == HTTPStatus.OK:
                video_url = response.output.video_url
                logger.info(f"Видео готово: {video_url}")
                return video_url
            else:
                error_msg = f"Status: {response.status_code}, Code: {response.code}, Message: {response.message}"
                logger.error(f"[{get_timestamp()}] Ошибка генерации видео: {error_msg}")
                return None
                
        except asyncio.TimeoutError:
            logger.error(f"[{get_timestamp()}] Таймаут генерации видео ({self.max_polling_time} сек)")
            return None
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Ошибка ожидания видео: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    @staticmethod
    async def download_video(video_url: str) -> bytes:
        """
        Скачивает видео по URL
        
        Args:
            video_url: URL видео из Alibaba
            
        Returns:
            Байты видео
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(video_url)
                response.raise_for_status()
                video_data = response.content
            
            video_size_mb = len(video_data) / (1024 * 1024)
            logger.info(f"Видео скачано ({video_size_mb:.2f} MB)")
            return video_data
            
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Ошибка скачивания видео: {e}")
            raise RuntimeError(f"Ошибка скачивания видео: {str(e)}")

