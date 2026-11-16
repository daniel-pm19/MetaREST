FROM python:3.12-slim
WORKDIR /sut
COPY sut-demo/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home metarest
COPY sut-demo/app.py ./app.py
USER metarest
EXPOSE 8001
CMD ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
