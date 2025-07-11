from concurrent import futures
import grpc
import threading
import proto.chess_pb2 as chess_pb2
import proto.chess_pb2_grpc as chess_pb2_grpc

# @author: Gustavo Alexandre de Assis Reino

# Criado em 03/07/2025

# Server that handles communication between game servers and clients

# Class that stores server and game data
class ChessServer:
    def __init__(self, ip: str, port: int):
        self.IP = ip
        self.PORT = port
        self.is_waiting_white = True
        self.is_game_active = False
        self.white_callback_url = None
        self.player_white_ip = ""
        self.player_black_ip = ""

    def add_player_white(self, white_ip: str, white_port: int, callback_url):
        self.is_waiting_white = False
        self.player_white_ip = white_ip
        self.player_white_port = white_port
        self.white_callback_url = callback_url

    def add_player_black(self, black_ip: str, black_port: int, callback_url):
        self.is_game_active = True
        self.player_black_ip = black_ip
        self.player_black_port = black_port
        self.black_callback_url = callback_url

    def reset(self):
        self.is_waiting_white = True
        self.is_game_active = False
        self.white_callback_url = None
        self.player_white_ip = ""
        self.player_black_ip = ""
        self.white_callback_url = ""
        self.black_callback_url = ""

    def __repr__(self):
        return f"Server(IP='{self.IP}', PORT={self.PORT})"
    
# Implementation of requests and responses
class ChessService(chess_pb2_grpc.ChessServiceServicer):
    def __init__(self):
        self.lock = threading.Lock()
        self.chess_servers = [
            ChessServer("192.168.100.101", 50051),
            ChessServer("192.168.100.102", 50051),
            ChessServer("192.168.100.103", 50051)
        ]
        self.condition = threading.Condition(self.lock)

    def FindGame(self, request, context):
        ip = request.client_ip
        port = request.client_port
        callback_url = request.callback_url

        with self.condition:
            for server in self.chess_servers:
                if not server.is_game_active:
                    if server.is_waiting_white:
                        server.add_player_white(ip, port, callback_url)
                        print(f"[+] Player {ip}:{port} joined as white on {server}")

                        # Wait for black to connect
                        while not server.is_game_active:
                            print(f"[ ] White is waiting for black on {server}")
                            self.condition.wait(timeout=6000)

                        # After black joins
                        return chess_pb2.FindGameResponse(
                            status="match found",
                            color="white",
                            server_ip=server.IP,
                            server_port=server.PORT
                        )
                    else:
                        server.add_player_black(ip, port,callback_url)
                        print(f"[+] Player {ip}:{port} joined as black on {server}")
                        self.condition.notify_all()

                        # Sends StartGame to Ruby chess server
                        self.send_start_game(server.IP, server.PORT)

                        return chess_pb2.FindGameResponse(
                            status="match found",
                            color="black",
                            server_ip=server.IP,
                            server_port=server.PORT
                        )

        return chess_pb2.FindGameResponse(
            status="no available servers",
            color="none",
            server_ip="",
            server_port=0
        )

    def Move(self, request, context):
        client_ip = request.client_ip
        client_port = request.client_port
        move = request.move
        color = request.color

        print(f"[>] Received move from {client_ip}:{client_port} as {color}: {move}")

        # Searches for the correct ChessServer
        matched_server = None
        for s in self.chess_servers:
            if (s.player_white_ip == client_ip and str(s.player_white_port) == str(client_port)) or \
            (s.player_black_ip == client_ip and str(s.player_black_port) == str(client_port)):
                matched_server = s
                break

        if matched_server is None:
            return chess_pb2.MoveResponse(
                status="No matching server found for this player",
                game=""
            )
        opponent_url = (
            matched_server.black_callback_url if color.lower() == "white" else matched_server.white_callback_url
        )

        if matched_server.player_white_ip == client_ip or matched_server.player_black_ip == client_ip:
            # Connects to the remote Ruby chess server via gRPC
            try:
                channel = grpc.insecure_channel(f"{matched_server.IP}:{matched_server.PORT}")
                stub = chess_pb2_grpc.ChessServiceStub(channel)

                # Sends move to the Ruby server
                response = stub.Move(chess_pb2.MoveRequest(
                    client_ip=client_ip,
                    client_port=client_port,
                    move=move,
                    color=color
                ))

                # Sends updated board to the other player
                try:
                    cb_channel = grpc.insecure_channel(opponent_url)
                    cb_stub = chess_pb2_grpc.ClientCallbackStub(cb_channel)

                    cb_stub.BoardUpdate(chess_pb2.BoardUpdateRequest(
                        message=response.status,
                        board=response.game
                    ))
                    print(f"[✓] Sent board update to opponent at {opponent_url}")
                except Exception as e:
                    print(f"[!] Failed to send update to opponent at {opponent_url}: {e}")

                # If match ends, server is set to vacant
                if "Checkmate" in response.status or "Stalemate" in response.status:
                    print(f"[!] Match ended: {response.status}, resetting {matched_server}")
                    matched_server.reset()

                # Responds to Client
                print(f"[✓] Forwarded move to {matched_server.IP}: {response.status}")
                return chess_pb2.MoveResponse(
                    status=response.status,
                    game=response.game
                )

            except Exception as e:
                print(f"[!] Failed to forward move to {matched_server.IP}:{matched_server.PORT} {e}")
                return chess_pb2.MoveResponse(
                    status="Error contacting game server",
                    game=""
                )

        # No matching server found
        print(f"[!] No matching game found for {client_ip}:{client_port}")
        return chess_pb2.MoveResponse(
            status="No active game",
            game=""
        )

    def Forfeit(self, request, context):

        client_ip = request.client_ip
        client_port = request.client_port
        color = request.color
        
        matched_server = None
        for s in self.chess_servers:
            if (s.player_white_ip == client_ip and str(s.player_white_port) == str(client_port)) or \
            (s.player_black_ip == client_ip and str(s.player_black_port) == str(client_port)):
                matched_server = s
                break

        if matched_server is None:
            return chess_pb2.ForfeitResponse(
                status="Error",
                message="No matching server found for this player"
            )
        opponent_url = (
            matched_server.black_callback_url if color.lower() == "white" else matched_server.white_callback_url
        )

        if matched_server.player_white_ip == client_ip or matched_server.player_black_ip == client_ip:
            # Connects to the remote chess logic server via gRPC
            try:
                channel = grpc.insecure_channel(f"{matched_server.IP}:{matched_server.PORT}")
                stub = chess_pb2_grpc.ChessServiceStub(channel)

                # Sends forfeit request to the chess logic server
                response = stub.Forfeit(chess_pb2.ForfeitRequest(
                    client_ip=client_ip,
                    client_port=client_port,
                    color=color
                ))

                # Sends forfeit message to the other player
                try:
                    cb_channel = grpc.insecure_channel(opponent_url)
                    cb_stub = chess_pb2_grpc.ClientCallbackStub(cb_channel)

                    cb_stub.BoardUpdate(chess_pb2.BoardUpdateRequest(
                        message= request.color+" forfeited!",
                        board=""
                    ))
                    print(f"[✓] Sent forfeit update to opponent at {opponent_url}")
                except Exception as e:
                    print(f"[!] Failed to send update to opponent at {opponent_url}: {e}")
        
                print(f"[✓] Forwarded move to {matched_server.IP}: {response.status}")

                # If match ends, server is set to vacant
                if "Checkmate" in response.status or "Stalemate" in response.status:
                    print(f"[!] Match ended: {response.status}, resetting {matched_server}")
                    matched_server.reset()
                
                # Responds to the client
                return chess_pb2.ForfeitResponse(
                    status=response.status,
                    message=response.message
                )

            except Exception as e:
                print(f"[!] Failed to forward move to {matched_server.IP}:{matched_server.PORT} {e}")
                return chess_pb2.ForfeitResponse(
                    status="Error contacting game server",
                    message=""
                )

        self.game.active = False
        # No matching server found
        print(f"[!] No matching game found for {client_ip}:{client_port}")
        return chess_pb2.ForfeitResponse(
            status="Error",
            message="No active game"
        )
    
    def send_start_game(self, ip, port):
        try:
            channel = grpc.insecure_channel(f"{ip}:{port}")
            stub = chess_pb2_grpc.ChessServiceStub(channel)
            response = stub.StartGame(chess_pb2.StartGameRequest())
            print(f"[✓] Started game on {ip}:{port}, board = {response.game}")
        except Exception as e:
            print(f"[!] Failed to start game on {ip}:{port}: {e}")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chess_pb2_grpc.add_ChessServiceServicer_to_server(ChessService(), server)
    server.add_insecure_port('[::]:50051')
    print("[gRPC] Server listening on port 50051")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
