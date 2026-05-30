"""Внешние сервисы (YOLO, YandexGPT, SpeechKit, Object Storage).

Каждый сервис имеет две реализации:
  • «стаб» — детерминированная заглушка, работает без облака (для локальной
    разработки и тестов);
  • «yandex» — реальный вызов API Yandex Cloud, включается при наличии ключей
    в переменных окружения (см. app/config.py).
Выбор реализации — по флагам *_configured в Settings.
"""


class UpstreamError(Exception):
    """Сбой внешнего сервиса. Маппится на HTTP 502 в app/main.py."""

    def __init__(self, message: str = "Внешний сервис временно недоступен.") -> None:
        super().__init__(message)
        self.message = message
