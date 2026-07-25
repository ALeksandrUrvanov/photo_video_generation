import asyncio
import base64
from io import BytesIO
from typing import List
from PIL import Image

from openai import AsyncOpenAI
from openai import APIError as OpenAIAPIError

from app.utils.logger import get_logger
from app.utils.datetime_utils import get_timestamp
from config.config import OPENROUTER_BANANA_CONFIG

logger = get_logger(__name__)


class PhotoVideoGenerationService:
    """Сервис генерации фото и видео через OpenRouter API"""
    
    def __init__(
        self,
        api_key: str,
        model_name: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_long_side: int | None = None,
    ):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers={
                "HTTP-Referer": OPENROUTER_BANANA_CONFIG.get("site_url") or "",
                "X-Title": OPENROUTER_BANANA_CONFIG.get("site_name") or "",
            }
        )
        # Читаем параметры из конфига, а переданные аргументы имеют приоритет
        self.model_name = model_name or OPENROUTER_BANANA_CONFIG.get("model_name")
        self.max_tokens = max_tokens if max_tokens is not None else OPENROUTER_BANANA_CONFIG.get("max_tokens")
        self.temperature = temperature if temperature is not None else OPENROUTER_BANANA_CONFIG.get("temperature")
        self.max_long_side = max_long_side if max_long_side is not None else OPENROUTER_BANANA_CONFIG.get("max_long_side")
    
    def encode_image(self, image_data: bytes) -> str:
        """Кодирует изображение в base64 с оптимизацией размера"""
        input_buf = BytesIO(image_data)
        
        try:
            with Image.open(input_buf) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    processed_im = im.convert("RGBA")
                else:
                    processed_im = im.convert("RGB")
                
                w, h = processed_im.size
                long_side = max(w, h)
                
                if long_side > self.max_long_side:
                    scale = self.max_long_side / float(long_side)
                    new_w, new_h = int(w * scale), int(h * scale)
                    processed_im = processed_im.resize((new_w, new_h), Image.LANCZOS)
                
                output_buf = BytesIO()
                try:
                    processed_im.save(output_buf, format="PNG", optimize=False)
                    output_buf.seek(0)
                    return base64.b64encode(output_buf.read()).decode('utf-8')
                finally:
                    output_buf.close()
                    if processed_im is not im:
                        processed_im.close()
        finally:
            input_buf.close()
    
    @staticmethod
    def _extract_image_from_response(response) -> str | None:
        """Извлекает URL сгенерированного изображения из ответа API"""
        if not response.choices or not hasattr(response.choices[0].message, 'images'):
            return None
        
        images = response.choices[0].message.images
        if not images:
            return None
        
        for img_obj in images:
            if not isinstance(img_obj, dict):
                continue

            img_url = None
            if 'image_url' in img_obj:
                image_url_obj = img_obj['image_url']
                if isinstance(image_url_obj, dict) and 'url' in image_url_obj:
                    img_url = image_url_obj['url']
                elif isinstance(image_url_obj, str):
                    img_url = image_url_obj
            elif 'url' in img_obj:
                img_url = img_obj['url']

            if isinstance(img_url, str) and img_url.startswith('data:image'):
                return img_url
        
        return None
    
    async def generate_photo(self, image_files: List[bytes], prompt: str) -> str:
        """Генерирует одно фото через OpenRouter API"""
        logger.info(f"[{get_timestamp()}] Начало генерации фото")
        
        encoded_images_list = None
        encoded_images = None
        chat_messages = None
        
        try:
            encode_tasks = [
                asyncio.to_thread(self.encode_image, image_data)
                for image_data in image_files
            ]
            
            encoded_images_list = await asyncio.gather(*encode_tasks)
            
            encoded_images = []
            for encoded_img in encoded_images_list:
                encoded_images.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded_img}"}
                })
            
            chat_messages = [{
                "role": "user",
                "content": [{"type": "text", "text": prompt}] + encoded_images
            }]
            
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=chat_messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            # Извлекаем изображение из ответа API
            result = self._extract_image_from_response(response)
            
            if result is None:
                raise RuntimeError("Не удалось получить сгенерированное изображение из ответа API")
            
            return result
            
        except (OpenAIAPIError, RuntimeError) as e:
            logger.error(f"[{get_timestamp()}] Ошибка генерации фото: {e}")
            raise
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Неожиданная ошибка генерации фото: {e}")
            raise RuntimeError(f"Ошибка генерации фото: {str(e)}") from e
        finally:
            if encoded_images_list is not None:
                del encoded_images_list
            if encoded_images is not None:
                del encoded_images
            if chat_messages is not None:
                del chat_messages
    
    @staticmethod
    def decode_base64_image(base64_string: str) -> bytes:
        """Декодирует base64 строку в байты изображения"""
        if base64_string.startswith('data:image'):
            base64_string = base64_string.split(',', 1)[1]
        return base64.b64decode(base64_string)