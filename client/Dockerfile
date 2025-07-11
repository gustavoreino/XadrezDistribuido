FROM golang:1.23

WORKDIR /app
COPY . .

RUN go build -o client main.go

CMD ["./client"]
