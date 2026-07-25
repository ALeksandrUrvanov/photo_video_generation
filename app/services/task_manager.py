import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass, field

from app.utils.logger import get_logger
from app.utils.datetime_utils import get_timestamp

logger = get_logger(__name__)


@dataclass
class VideoTask:
    """Модель задачи генерации видео"""
    task_id: str
    alibaba_task_id: str
    client_id: str
    status: str  # PROCESSING, SUCCEEDED, FAILED
    photo_url: str
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def update_status(self, status: str, video_url: Optional[str] = None, error_message: Optional[str] = None):
        """Обновляет статус задачи"""
        self.status = status
        self.updated_at = datetime.now()
        if video_url:
            self.video_url = video_url
        if error_message:
            self.error_message = error_message


class TaskManager:
    """Управление состоянием задач генерации видео"""
    
    def __init__(self, cleanup_interval: int = 3600):
        """
        Args:
            cleanup_interval: Интервал очистки старых задач (в секундах)
        """
        self._tasks: Dict[str, VideoTask] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start_cleanup(self):
        """Запускает фоновую очистку старых задач"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_cleanup(self):
        """Останавливает фоновую очистку"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("TaskManager: фоновая очистка остановлена")
    
    async def _cleanup_loop(self):
        """Цикл очистки старых задач (старше 24 часов)"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_old_tasks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в cleanup loop: {e}")
    
    async def _cleanup_old_tasks(self):
        """Удаляет задачи старше 24 часов"""
        async with self._lock:
            now = datetime.now()
            expired_threshold = now - timedelta(hours=24)
            
            tasks_to_remove = [
                task_id for task_id, task in self._tasks.items()
                if task.created_at < expired_threshold
            ]
            
            for task_id in tasks_to_remove:
                del self._tasks[task_id]
            
            if tasks_to_remove:
                logger.info(f"TaskManager: удалено {len(tasks_to_remove)} старых задач")
    
    async def create_task(
        self,
        task_id: str,
        alibaba_task_id: str,
        client_id: str,
        photo_url: str
    ) -> VideoTask:
        """Создает новую задачу"""
        async with self._lock:
            task = VideoTask(
                task_id=task_id,
                alibaba_task_id=alibaba_task_id,
                client_id=client_id,
                status="PROCESSING",
                photo_url=photo_url
            )
            self._tasks[task_id] = task
            logger.info(f"TaskManager: создана задача {task_id}")
            return task
    
    async def get_task(self, task_id: str) -> Optional[VideoTask]:
        """Получает задачу по ID"""
        async with self._lock:
            return self._tasks.get(task_id)
    
    async def update_task(
        self,
        task_id: str,
        status: str,
        video_url: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> Optional[VideoTask]:
        """Обновляет статус задачи"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.update_status(status, video_url, error_message)
                logger.info(f"TaskManager: обновлена задача {task_id}, статус: {status}")
            return task
    
    async def get_task_count(self) -> int:
        """Возвращает количество активных задач"""
        async with self._lock:
            return len(self._tasks)

