FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 复制 Python 代码（不复制你的配置和 dashboard.html）
COPY . /app/
RUN rm -f /app/config.json /app/dashboard.html

CMD ["python", "netcup_monitor.py"]
