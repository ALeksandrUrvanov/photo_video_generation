from pathlib import Path
from typing import Optional
import logging

import zxingcpp
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


def decode_datamatrix(image_path: str) -> Optional[str]:
    """
    Распознать DataMatrix код из изображения

    Args:
        image_path: Путь к изображению

    Returns:
        УИН (16-значный код) или None если не распознан
    """
    try:
        # Проверка существования файла
        if not Path(image_path).exists():
            logger.error(f"Файл не найден: {image_path}")
            return None

        # Чтение изображения через PIL
        pil_image = Image.open(image_path)

        if pil_image is None:
            logger.error(f"Не удалось прочитать изображение: {image_path}")
            return None

        # Конвертация в RGB если нужно
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')

        # Конвертация PIL в numpy array для zxing-cpp
        img_array = np.array(pil_image)

        # Распознавание DataMatrix через zxing-cpp
        results = zxingcpp.read_barcodes(img_array)

        # Фильтруем только DataMatrix результаты
        datamatrix_results = [r for r in results if r.valid and r.format == zxingcpp.BarcodeFormat.DataMatrix]

        if datamatrix_results:
            uin = datamatrix_results[0].text
            logger.info(f"DataMatrix распознан: {uin}")
            return uin

        logger.warning("DataMatrix код не найден на изображении")
        return None

    except Exception as e:
        logger.exception(f"Ошибка распознавания DataMatrix: {e}")
        return None
