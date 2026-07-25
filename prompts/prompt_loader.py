import os

from app.utils.logger import get_logger

logger = get_logger(__name__)


class PromptLoader:
    """Загрузчик промптов"""
    
    _prompts_dir = os.path.join(os.path.dirname(__file__))
    
    @classmethod
    def load_prompt(cls, prompt_name: str) -> str:
        """Загружает промпт по имени файла"""
        prompt_file = os.path.join(cls._prompts_dir, f"{prompt_name}.md")
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.error(f"Файл промпта не найден: {prompt_file}")
            raise FileNotFoundError(f"Файл промпта не найден: {prompt_file}")
        except Exception as e:
            logger.error(f"Ошибка загрузки промпта '{prompt_name}': {e}")
            raise RuntimeError(f"Ошибка загрузки промпта '{prompt_name}': {e}")
    
    @classmethod
    def get_photo_generation_lifestyle_prompt(cls) -> str:
        """Получение промпта для генерации фото в стиле lifestyle"""
        return cls.load_prompt("photo_generation_lifestyle")
    
    @classmethod
    def get_video_prompt_generation_instruction(cls) -> str:
        """Получение инструкции для Gemini-3-Pro по созданию промптов для видео"""
        return cls.load_prompt("video_prompt_generation")