FROM ruby:3.2

WORKDIR /app

# Copy files
COPY . /app

# Install dependencies
RUN gem install grpc grpc-tools chess google-protobuf && grpc_tools_ruby_protoc -I proto   --ruby_out=lib   --grpc_out=lib   proto/chess.proto
    

EXPOSE 50051

CMD ["ruby", "server.rb"]
