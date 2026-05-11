# Инструкция по запуску
## 1. Запуск bot.py
```python
cd ~/"Visual Studio Code/devichyi_dela_bot"
source venv/bin/activate
python3 bot.py
```

## 2. Запуск admin_web.py
```python
cd ~/"Visual Studio Code/devichyi_dela_bot"
source venv/bin/activate
uvicorn admin_web:app --reload --port 8000
```

> Для запуска двух файлов одновременно необходимо два окна терминала