# Обычный запуск (продолжает с места остановки)
python parser.py

# Перекачать всё заново
python parser.py --force

# Спарсить только конкретную ветку/страницу
python parser.py --node=0a005eed82e84ec78eca8a7e3ece534a

--node работает по id любого узла (папки или листа). Если это папка — обход пойдёт по её поддереву, если лист — только эта страница.

# Если ок — основной скрипт
python translate.py

# Только content.json
python translate.py --content

# Только страницы
python translate.py --pages