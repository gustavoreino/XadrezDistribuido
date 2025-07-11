require 'chess'
require 'grpc'
$LOAD_PATH.unshift(File.expand_path('lib', __dir__))
require_relative 'lib/chess_pb'
require_relative 'lib/chess_services_pb'

# @author: Gustavo Alexandre de Assis Reino

# Criado em 04/07/2025

# Chess game logic gRPC server

# Declares a service to handle requests
class ChessServiceHandler < Chess::ChessService::Service
  def initialize
    @game = Chess::Game.new # Initializes a game
  end
  # Responds to the start game request
  def start_game(_req, _unused_call)
    puts "Game started"
    Chess::StartGameResponse.new(game: @game.board.to_s)
  end

  def move(move_request, _unused_call)
  move = move_request.move
  color = move_request.color.downcase.strip  # "white" or "black"

    begin
        # Determine current turn
        current_turn = (@game.moves.length.even?) ? "white" : "black"

        unless color == current_turn
          # Responds the request denying the out of turn move
          return Chess::MoveResponse.new(
            status: "It's not your turn (current turn: #{current_turn})",
            game: @game.board.to_s
          )
        end

        if @game.move(move)
          
          if @game.board.checkmate? # Checks if this move caused checkmate
            return Chess::MoveResponse.new(
              status: "Checkmate! #{color.capitalize} wins!",
              game: @game.board.to_s
            )
          elsif @game.board.stalemate? # Checks if this move caused stalemate
            return Chess::MoveResponse.new(
              status: "Game drawn by stalemate",
              game: @game.board.to_s
            )
          else # Responds to the request confirming the move was accepted
            return Chess::MoveResponse.new(
              status: "Move accepted",
              game: @game.board.to_s
            )
          end
        else
          # Responds the request denying the illegal move
          return Chess::MoveResponse.new(
            status: "Illegal move",
            game: @game.board.to_s
          )
      end

    rescue => e
      return Chess::MoveResponse.new(
        status: "Error: #{e.message}",
        game: @game.board.to_s
      )
    end
  end
  # Responds to forfeit request
  def forfeit(_req, _unused_call)
    puts "Player forfeited"
    game = Chess::Game.new # Restarts game
    Chess::ForfeitResponse.new(status: "forfeit accepted", message: "#{_req.color} forfeited")
  end
end

# Runs server
def main
  port = '0.0.0.0:50051'
  puts "Starting Ruby Chess gRPC Server on #{port}..."
  server = GRPC::RpcServer.new
  server.add_http2_port(port, :this_port_is_insecure)
  server.handle(ChessServiceHandler)
  server.run_till_terminated
end

main if __FILE__ == $0