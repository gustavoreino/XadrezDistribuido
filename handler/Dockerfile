FROM python:3.12.2

WORKDIR /app
COPY . .

RUN pip install grpcio grpcio-tools handler

EXPOSE 4443
CMD ["python", "handler_grpc.py"]
