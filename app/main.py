import time
import os
import asyncio
import uuid
import httpx
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from openai import APIError as OpenAIAPIError

from app.services.webhook_schemas import (
    PhotoGenerationRequest,
    PhotoGenerationResponse,
    PhotoGenerationData,
    VideoGenerationRequest,
    VideoGenerationInitResponse,
    VideoStatusResponse,
    VideoGenerationData,
    ErrorInfo
)
from app.services.photo_generation_service import PhotoVideoGenerationService
from app.services.prompt_generation_service import PromptGenerationService
from app.services.video_generation_service import VideoGenerationService
from app.services.task_manager import TaskManager
from app.utils.logger import get_logger
from app.utils.datetime_utils import get_timestamp
from app.utils.response_utils import create_error_response, ErrorStatus
from prompts.prompt_loader import PromptLoader
from config.config import (
    OPENROUTER_BANANA_CONFIG, OPENROUTER_PROMPT_CONFIG,
    ALIBABA_WAN_CONFIG, PHOTO_GENERATION_CONFIG,
    SERVICE_NAME, MAX_FILE_SIZE_MB, BYTES_TO_MB_DIVISOR,
    MAX_CONCURRENT_PHOTO_TASKS, MAX_CONCURRENT_VIDEO_TASKS,
    GENERATED_FILES_BASE_URL
)
from app.services.file_storage import save_generated_file
from database.photo_gen_tracker import save_generated_file as save_to_csv

logger = get_logger(__name__)

# Константы для оптимизации
SUPPORTED_FORMATS = PHOTO_GENERATION_CONFIG.get("supported_formats")

# Semaphore для ограничения одновременных задач генерации
photo_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PHOTO_TASKS)
video_semaphore = asyncio.Semaphore(MAX_CONCURRENT_VIDEO_TASKS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager для FastAPI приложения"""
    app.state.start_time = time.time()
    
    logger.info(f"[{get_timestamp()}] Запуск FastAPI сервера...")
    
    try:
        banana_api_key = OPENROUTER_BANANA_CONFIG.get("api_key")
        if not banana_api_key:
            raise ValueError("OPENROUTER_API_KEY_BANANA не установлен в переменных окружения")
        
        app.state.photo_service = PhotoVideoGenerationService(
            api_key=banana_api_key,
            model_name=OPENROUTER_BANANA_CONFIG.get("model_name")
        )
        logger.info(f"[{get_timestamp()}] PhotoVideoGenerationService (Gemini 2.5 Flash) инициализирован")
        
        prompt_api_key = OPENROUTER_PROMPT_CONFIG.get("api_key")
        if not prompt_api_key:
            raise ValueError("OPENROUTER_API_KEY_PROMPT не установлен в переменных окружения")
        
        app.state.prompt_service = PromptGenerationService(
            api_key=prompt_api_key,
            model_name=OPENROUTER_PROMPT_CONFIG.get("model_name")
        )
        logger.info(f"[{get_timestamp()}] PromptGenerationService (Claude Sonnet 4.5) инициализирован")
        
        alibaba_api_key = ALIBABA_WAN_CONFIG.get("api_key")
        if not alibaba_api_key:
            raise ValueError("API_KEY_WAN2.2_I2V_PLUS не установлен в переменных окружения")
        
        app.state.video_service = VideoGenerationService(
            api_key=alibaba_api_key,
            model=ALIBABA_WAN_CONFIG.get("model")
        )
        
        app.state.task_manager = TaskManager(cleanup_interval=3600)
        await app.state.task_manager.start_cleanup()
        logger.info(f"[{get_timestamp()}] TaskManager инициализирован")
        
        
        # Кэшируем промпты для оптимизации
        app.state.lifestyle_prompt = PromptLoader.get_photo_generation_lifestyle_prompt()
        app.state.video_prompt_instruction = PromptLoader.get_video_prompt_generation_instruction()
        logger.info(f"[{get_timestamp()}] Промпты загружены и кэшированы")
        
    except Exception as e:
        logger.error(f"[{get_timestamp()}] Ошибка инициализации сервисов: {e}")
        raise
    
    yield
    
    # Cleanup при завершении
    if hasattr(app.state, "task_manager"):
        await app.state.task_manager.stop_cleanup()
        logger.info(f"[{get_timestamp()}] TaskManager остановлен")


app = FastAPI(
    title="Photo Generation Service",
    description="Автоматическая генерация фотографий ювелирных изделий на модели",
    lifespan=lifespan
)


def _validate_request(
    photo_names: list[str], 
    photo_service: PhotoVideoGenerationService
) -> None:
    """Валидация запроса на генерацию фото"""
    if len(photo_names) < PHOTO_GENERATION_CONFIG["min_photos"]:
        raise ValueError(f"Минимальное количество фото: {PHOTO_GENERATION_CONFIG['min_photos']}")
    
    if len(photo_names) > PHOTO_GENERATION_CONFIG["max_photos"]:
        raise ValueError(f"Максимальное количество фото: {PHOTO_GENERATION_CONFIG['max_photos']}")
    
    if not photo_service:
        raise HTTPException(status_code=503, detail="Сервис недоступен")
    
    for photo_name in photo_names:
        file_ext = os.path.splitext(photo_name)[1].lower()
        if SUPPORTED_FORMATS and file_ext not in SUPPORTED_FORMATS:
            raise ValueError(f"Неподдерживаемый формат: {file_ext}. Поддерживаемые: {', '.join(SUPPORTED_FORMATS)}")


def _validate_file_size(image_data: bytes) -> None:
    """Валидация размера загруженного файла"""
    file_size_mb = len(image_data) / BYTES_TO_MB_DIVISOR
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(f"Размер файла {file_size_mb:.2f} MB превышает максимальный {MAX_FILE_SIZE_MB} MB")


async def _load_images_parallel(photo_names: list[str]) -> list[bytes]:
    """Параллельная загрузка изображений по HTTP URL"""
    async def _load_single_file(photo_url: str) -> bytes:
        """Загрузка одного файла по HTTP"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(photo_url)
            response.raise_for_status()
            return response.content
    
    download_tasks = [_load_single_file(url) for url in photo_names]
    image_files = await asyncio.gather(*download_tasks)
    
    for image_data in image_files:
        _validate_file_size(image_data)
    
    return image_files


async def _generate_image_with_ai(
    image_files: list[bytes], 
    photo_service: PhotoVideoGenerationService,
    prompt: str
) -> tuple[str, bytes]:
    """3. Генерация изображения через AI и декодирование из base64"""
    generated_image_base64 = await photo_service.generate_photo(image_files, prompt)
    
    logger.info(f"[{get_timestamp()}] Фото успешно сгенерировано")
    
    generated_image_bytes = photo_service.decode_base64_image(generated_image_base64)
    
    return generated_image_base64, generated_image_bytes


async def _save_generated_image(
    generated_image_bytes: bytes, 
    client_id: str
) -> tuple[str, str]:
    """4. Сохранение сгенерированного изображения на сервер"""
    # Сохраняем файл на РМП сервер и получаем URL + артикул РМП
    file_url, item_id = await save_generated_file(
        file_data=generated_image_bytes,
        uin=client_id,
        file_type="photo"
    )
    
    # Записываем информацию в локальный файл photo_gen.csv
    await save_to_csv(photo_url=file_url, item_id=item_id, uin=client_id)
    
    output_filename = f"{client_id}_10.jpg"
    
    return file_url, output_filename


def _cleanup_memory(
    image_files: Optional[list[bytes]], 
    generated_image_base64: Optional[str], 
    generated_image_bytes: Optional[bytes]
) -> None:
    """5. Очистка больших объектов из памяти"""
    if image_files:
        del image_files
    if generated_image_base64:
        del generated_image_base64
    if generated_image_bytes:
        del generated_image_bytes


def _handle_generation_error(e: Exception) -> tuple[ErrorStatus, str]:
    """6. Обработка ошибок генерации и определение типа ошибки"""
    if isinstance(e, (OpenAIAPIError, RuntimeError)):
        return ErrorStatus.GENERATION_ERROR, f"Ошибка генерации фото: {str(e)}"
    
    error_msg_lower = str(e).lower()
    if "generation" in error_msg_lower or ("image" in error_msg_lower and "api" in error_msg_lower):
        return ErrorStatus.GENERATION_ERROR, f"Ошибка генерации фото: {str(e)}"
    
    return ErrorStatus.SERVER_ERROR, f"Прочая ошибка: {str(e)}"


def _create_error_response_object(client_id: str, error_dict: dict) -> PhotoGenerationResponse:
    """7. Создание объекта ответа с ошибкой"""
    return PhotoGenerationResponse(
        id_client=client_id,
        data=PhotoGenerationData(
            generated_photo_url="",
            generated_photo_name=""
        ),
        error=ErrorInfo(**error_dict["error"])
    )


@app.post("/GeneratePhoto", response_model=PhotoGenerationResponse)
async def generate_photo(request: PhotoGenerationRequest) -> PhotoGenerationResponse:
    """
    Генерация фото изделия на человеке
    
    Используется ботом для первичной генерации фото.
    """
    start_time = time.time()
    client_id = request.id_client
    photo_names = request.photos
    item_type = request.item_type
    gender = request.gender
    
    logger.info(f"[{get_timestamp()}] Получен запрос от клиента {client_id}")
    logger.info(f"[{get_timestamp()}] Количество фото: {len(photo_names)}")
    if item_type:
        logger.info(f"[{get_timestamp()}] Тип изделия: {item_type}")
    if gender:
        logger.info(f"[{get_timestamp()}] Гендер: {gender}")
    
    image_files: Optional[list[bytes]] = None
    generated_image_base64: Optional[str] = None
    generated_image_bytes: Optional[bytes] = None
    
    # Получаем сервисы и кэшированные данные из app.state
    photo_service = app.state.photo_service
    lifestyle_prompt = app.state.lifestyle_prompt
    
    # Если переданы тип изделия или гендер, добавляем их в промпт
    if item_type or gender:
        # Вставляем информацию о типе изделия и гендере в секцию TASK
        item_info_line = "\n"
        if item_type:
            item_info_line += f"**ITEM TYPE:** {item_type}\n"
        if gender:
            item_info_line += f"**TARGET GENDER:** {gender}\n"
        
        # Находим секцию TASK и вставляем после неё
        if "TASK:" in lifestyle_prompt:
            parts = lifestyle_prompt.split("TASK:", 1)
            # Находим конец строки TASK (первый перенос после TASK:)
            task_parts = parts[1].split("\n", 1)
            lifestyle_prompt = parts[0] + "TASK:" + task_parts[0] + item_info_line + task_parts[1]
            logger.info(f"[{get_timestamp()}] Добавлена информация о типе изделия и гендере в промпт")
    
    async with photo_semaphore:
        logger.info(f"[{get_timestamp()}] [{client_id}] Получен слот для генерации фото (доступно: {photo_semaphore._value}/{MAX_CONCURRENT_PHOTO_TASKS})")
        
        try:
            # Валидация запроса
            _validate_request(photo_names, photo_service)
            
            # Параллельная загрузка изображений по HTTP
            image_files = await _load_images_parallel(photo_names)
            
            # Генерация изображения через AI (используем кэшированный промпт)
            generated_image_base64, generated_image_bytes = await _generate_image_with_ai(
                image_files, photo_service, lifestyle_prompt
            )
            
            # Сохранение сгенерированного изображения (используем client_id как УИН)
            generated_url, output_filename = await _save_generated_image(
                generated_image_bytes, client_id
            )
            
            # Получаем артикул РМП для записи в photo_gen.csv
            from app.services.file_storage import get_item_id_by_uin
            item_id = get_item_id_by_uin(client_id)
            
            # Сохранение в photo_gen.csv для интеграции с РМП (НОВЫЙ ФОРМАТ с uin)
            await save_to_csv(photo_url=generated_url, item_id=item_id, uin=client_id)
            logger.info(f"[{get_timestamp()}] Сохранено в photo_gen.csv: УИН={client_id}, URL={generated_url}")
            
            processing_time = time.time() - start_time
            logger.info(f"[{get_timestamp()}] Обработка завершена за {processing_time:.2f} сек")
            
            return PhotoGenerationResponse(
                id_client=client_id,
                data=PhotoGenerationData(
                    generated_photo_url=generated_url,
                    generated_photo_name=output_filename
                ),
                error=ErrorInfo(status=ErrorStatus.SUCCESS, detail="Успех")
            )
        
        except (ValueError, FileNotFoundError) as e:
            logger.error(f"[{get_timestamp()}] Ошибка валидации данных: {e}")
            
            error_dict = create_error_response(
                client_id=client_id,
                error_status=ErrorStatus.NO_DATA,
                error_message=f"Нет данных: {str(e)}"
            )
            
            return _create_error_response_object(client_id, error_dict)
    
        except Exception as e:
            logger.error(f"[{get_timestamp()}] Ошибка обработки: {e}")
            
            error_status, error_message = _handle_generation_error(e)
            
            error_dict = create_error_response(
                client_id=client_id,
                error_status=error_status,
                error_message=error_message
            )
            
            return _create_error_response_object(client_id, error_dict)
        
        finally:
            # Очистка памяти после обработки запроса
            _cleanup_memory(image_files, generated_image_base64, generated_image_bytes)
            
            logger.info(f"[{get_timestamp()}] [{client_id}] Слот освобождён (доступно: {photo_semaphore._value + 1}/{MAX_CONCURRENT_PHOTO_TASKS})")


@app.post("/GenerateVideo", response_model=VideoGenerationInitResponse)
async def generate_video(request: VideoGenerationRequest) -> VideoGenerationInitResponse:
    """
    Генерация видео из уже сгенерированного фото
    
    1. Создает задачу
    2. Запускает генерацию промпта + видео в фоне
    3. Возвращает task_id мгновенно для polling
    
    Требования:
    - Фото УЖЕ должно быть сгенерировано через /GeneratePhoto
    - URL фото: https://media.example.com/{УИН}_10.jpg
    """
    client_id = request.id_client
    task_id = str(uuid.uuid4())
    
    logger.info(f"[{get_timestamp()}] Получен запрос на генерацию видео для УИН {client_id}")
    
    prompt_service = app.state.prompt_service
    video_service = app.state.video_service
    task_manager = app.state.task_manager
    video_prompt_instruction = app.state.video_prompt_instruction
    
    try:
        # Регистрируем задачу в TaskManager
        await task_manager.create_task(
            task_id=task_id,
            alibaba_task_id="",
            client_id=client_id,
            photo_url=f"https://media.example.com/{client_id}_10.jpg"
        )
        
        # Запускаем генерацию видео в фоне (фото загружается из РМП)
        asyncio.create_task(_video_pipeline(
            task_id=task_id,
            client_id=client_id,
            prompt_service=prompt_service,
            video_service=video_service,
            task_manager=task_manager,
            video_prompt_instruction=video_prompt_instruction
        ))
        
        logger.info(f"[{get_timestamp()}] Генерация видео запущена в фоне")
        
        return VideoGenerationInitResponse(
            task_id=task_id,
            status="PROCESSING",
            message="Задача создана. Генерация видео в процессе. Проверяйте статус через /VideoStatus/{task_id}",
            estimated_completion_time=300,
            recommended_polling_delay=30
        )
    
    except Exception as e:
        logger.error(f"[{get_timestamp()}] Ошибка обработки видео: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _video_pipeline(
    task_id: str,
    client_id: str,
    prompt_service,
    video_service,
    task_manager,
    video_prompt_instruction: str
):
    """
    Пайплайн генерации видео из уже сгенерированного фото
    
    1. Загружает фото из РМП (https://media.example.com/{УИН}_10.jpg)
    2. Генерирует промпт
    3. Генерирует видео через Alibaba
    4. Сохраняет видео в РМП и в photo_gen.csv
    """
    generated_image_bytes: Optional[bytes] = None
    
    async with video_semaphore:
        try:
            # 1. Загрузка уже сгенерированного фото из РМП
            photo_url = f"{GENERATED_FILES_BASE_URL}/{client_id}_10.jpg"
            
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                response = await http_client.get(photo_url)
                response.raise_for_status()
                generated_image_bytes = response.content
            
            # Обновляем задачу с photo_url
            task = await task_manager.get_task(task_id)
            if task:
                task.photo_url = photo_url
            
            # 2. Генерация промпта через Claude (OpenRouter)
            video_prompt = await prompt_service.generate_video_prompt(
                generated_image_bytes,
                video_prompt_instruction
            )
            
            # 3. Создание задачи генерации видео в Alibaba Wan
            alibaba_task_id, task_status, task_response = await video_service.create_video_task(
                generated_image_bytes,
                video_prompt
            )
            
            # Обновляем задачу в TaskManager с alibaba_task_id
            task = await task_manager.get_task(task_id)
            if task:
                task.alibaba_task_id = alibaba_task_id
            
            # 4. Ожидание завершения генерации видео
            video_url_alibaba = await video_service.wait_for_video(task_response)
            
            if video_url_alibaba:
                # 5. Скачивание MP4 от Alibaba
                video_data = await video_service.download_video(video_url_alibaba)
                # 6. Сохранение видео (MP4) в РМП
                video_url_final, item_id = await save_generated_file(
                    file_data=video_data,
                    uin=client_id,
                    file_type="video"
                )
                
                # 7. Сохранение в photo_gen.csv для интеграции с РМП
                await save_to_csv(photo_url=video_url_final, item_id=item_id, uin=client_id)
                logger.info(f"[{task_id}] Видео сохранено: УИН={client_id}, URL={video_url_final}")
                
                # 8. Обновление статуса задачи
                await task_manager.update_task(
                    task_id=task_id,
                    status="SUCCEEDED",
                    video_url=video_url_final
                )
            else:
                await task_manager.update_task(
                    task_id=task_id,
                    status="FAILED",
                    error_message="Ошибка генерации видео: таймаут или ошибка Alibaba API"
                )
                logger.error(f"[{get_timestamp()}] [{task_id}] Видео не получено от Alibaba")
        
        except httpx.HTTPStatusError as e:
            error_msg = f"Фото не найдено в РМП: {photo_url} (код {e.response.status_code})"
            logger.error(f"[{get_timestamp()}] [{task_id}] {error_msg}")
            await task_manager.update_task(
                task_id=task_id,
                status="FAILED",
                error_message=error_msg
            )
        except Exception as e:
            logger.error(f"[{get_timestamp()}] [{task_id}] Ошибка в пайплайне видео: {e}")
            await task_manager.update_task(
                task_id=task_id,
                status="FAILED",
                error_message=f"Ошибка: {str(e)}"
            )
        
        finally:
            if generated_image_bytes:
                del generated_image_bytes


@app.get("/VideoStatus/{task_id}", response_model=VideoStatusResponse)
async def get_video_status(task_id: str) -> VideoStatusResponse:
    """
    Проверка статуса задачи генерации видео
    
    Возвращает:
    - PROCESSING: генерация в процессе
    - SUCCEEDED: фото и видео готовы
    - FAILED: только фото (ошибка генерации видео)
    """
    task_manager = app.state.task_manager
    
    task = await task_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
    
    if task.status == "SUCCEEDED":
        return VideoStatusResponse(
            task_id=task_id,
            status="SUCCEEDED",
            data=VideoGenerationData(
                photo_url=task.photo_url,
                video_url=task.video_url
            ),
            error=ErrorInfo(status=0, detail="Успех")
        )
    elif task.status == "FAILED":
        return VideoStatusResponse(
            task_id=task_id,
            status="FAILED",
            data=VideoGenerationData(
                photo_url=task.photo_url,
                video_url=None
            ),
            error=ErrorInfo(status=2, detail=task.error_message or "Ошибка генерации видео")
        )
    else:
        return VideoStatusResponse(
            task_id=task_id,
            status="PROCESSING",
            data=VideoGenerationData(
                photo_url=task.photo_url,
                video_url=None
            ),
            error=ErrorInfo(status=0, detail="Генерация в процессе")
        )


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Проверка состояния сервиса"""
    uptime_seconds = time.time() - app.state.start_time
    
    task_count = 0
    if hasattr(app.state, "task_manager"):
        task_count = await app.state.task_manager.get_task_count()
    
    # Вычисляем количество активных обработок для фото и видео
    photo_available_slots = photo_semaphore._value
    photo_active_processing = MAX_CONCURRENT_PHOTO_TASKS - photo_available_slots
    
    video_available_slots = video_semaphore._value
    video_active_processing = MAX_CONCURRENT_VIDEO_TASKS - video_available_slots
    
    health_status = {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": get_timestamp(),
        "uptime_seconds": round(uptime_seconds, 2),
        "photo_service": "initialized" if hasattr(app.state, "photo_service") else "not initialized",
        "prompt_service": "initialized" if hasattr(app.state, "prompt_service") else "not initialized",
        "video_service": "initialized (Alibaba)" if hasattr(app.state, "video_service") else "not initialized",
        "task_manager": "initialized" if hasattr(app.state, "task_manager") else "not initialized",
        "active_tasks": task_count,
        "photo_generation": {
            "concurrent_limit": MAX_CONCURRENT_PHOTO_TASKS,
            "active_processing": photo_active_processing,
            "available_slots": photo_available_slots,
            "queue_status": "busy" if photo_available_slots == 0 else "available"
        },
        "video_generation": {
            "concurrent_limit": MAX_CONCURRENT_VIDEO_TASKS,
            "active_processing": video_active_processing,
            "available_slots": video_available_slots,
            "queue_status": "busy" if video_available_slots == 0 else "available"
        }
    }
    
    return health_status