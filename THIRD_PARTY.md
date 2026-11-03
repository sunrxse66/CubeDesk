# Компоненты и лицензии

CubeDesk распространяется под GPL-3.0-or-later. Полный текст — в LICENSE.

- Прошивка основана на [Times-Z/GeekMagic-Open-Firmware](https://github.com/Times-Z/GeekMagic-Open-Firmware), commit a0c2ddcef4e76fa6eb040f6f544124763a2d85f5, GPL-3.0-or-later. Исходные уведомления об авторстве сохранены.
- [QR-Code-generator](https://github.com/nayuki/QR-Code-generator/tree/v1.8.0), Project Nayuki, v1.8.0, MIT. Исходники и текст лицензии включены в firmware/lib/qrcodegen.
- [Python](https://www.python.org/psf/license/), PSF License. Готовое приложение включает интерпретатор Python через PyInstaller.
- [Pillow](https://github.com/python-pillow/Pillow/blob/main/LICENSE), HPND и лицензии включённых компонентов. Используется для обработки изображений и рисования виджетов.
- [PyInstaller](https://pyinstaller.org/en/stable/license.html), GPL с исключением для собранных приложений.
- Зависимости ESP8266 Arduino, ArduinoJson, Arduino_GFX, AnimatedGIF и TJpg_Decoder зафиксированы в firmware/platformio.ini. Их авторство и лицензии находятся в соответствующих исходных проектах и сохраняются при сборке PlatformIO.
- Погода и геокодирование: [Open-Meteo](https://open-meteo.com/) и [GeoNames](https://www.geonames.org/). В интерфейсе есть указание источников. Для коммерческого распространения проверьте действующие условия API Open-Meteo.

Моти, интерфейс и графика виджетов рисуются кодом. Пользовательские картинки, GIF, шрифты Windows и личные настройки в репозиторий не включаются. Для текста на Windows используются установленные системные шрифты.
