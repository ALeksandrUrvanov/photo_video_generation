import base64
from io import BytesIO
from PIL import Image

from openai import AsyncOpenAI
from openai import APIError as OpenAIAPIError

from app.utils.logger import get_logger
from app.utils.datetime_utils import get_timestamp
from config.config import OPENROUTER_PROMPT_CONFIG

logger = get_logger(__name__)


class PromptGenerationService:
    """Сервис генерации промптов для видео через OpenRouter (Claude Sonnet 4.5)"""
    
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
                "HTTP-Referer": OPENROUTER_PROMPT_CONFIG.get("site_url") or "",
                "X-Title": OPENROUTER_PROMPT_CONFIG.get("site_name") or "",
            }
        )
        self.model_name = model_name or OPENROUTER_PROMPT_CONFIG.get("model_name")
        self.max_tokens = max_tokens if max_tokens is not None else OPENROUTER_PROMPT_CONFIG.get("max_tokens")
        self.temperature = temperature if temperature is not None else OPENROUTER_PROMPT_CONFIG.get("temperature")
        self.max_long_side = max_long_side if max_long_side is not None else OPENROUTER_PROMPT_CONFIG.get("max_long_side")
    
    def encode_image(self, image_data: bytes) -> str:
        """Кодирует изображение в base64 с оптимизацией размера для Claude"""
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
    def create_image_message(encoded_img: str) -> dict:
        """Создание структуры сообщения с изображением"""
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encoded_img}"}
        }
    
    async def generate_video_prompt(
        self, 
        image_data: bytes, 
        system_instruction: str
    ) -> str:
        """
        Генерирует промпт для видео на основе изображения
        
        Args:
            image_data: Байты изображения (сгенерированное фото ювелирного изделия)
            system_instruction: Инструкция по формированию промпта
            
        Returns:
            Промпт для генерации видео в формате Alibaba Wan
        """
        try:
            encoded_img = self.encode_image(image_data)
            image_message = self.create_image_message(encoded_img)
            
            chat_messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": system_instruction},
                    image_message
                ]
            }]
            
            # Подготовка параметров запроса
            request_params = {
                "model": self.model_name,
                "messages": chat_messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }
            
            response = await self.client.chat.completions.create(**request_params)
            message = response.choices[0].message

            if message.content:
                result = message.content
            elif hasattr(message, 'reasoning') and message.reasoning:
                result = message.reasoning
            else:
                raise RuntimeError("Не удалось получить промпт от модели")

            logger.info("Промпт для видео сгенерирован")
            return result

        except (OpenAIAPIError, RuntimeError) as e:
            logger.error(f"[{get_timestamp()}] Ошибка генерации промпта (Claude/OpenRouter): {e}")
            raise
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Неожиданная ошибка генерации промпта: {e}")
            raise RuntimeError(f"Ошибка генерации промпта: {str(e)}") from e

