package main

import (
	"bufio"
	"fmt"
	"context"
	"os"
	"strings"
	"log"
	"time"
	"net"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	pb "chess/client/proto/chesspb"
	"os/signal"
	"syscall"
)

// @author Gustavo Alexandre de Assis Reino

// Criado em 03/07/2025

// CLI Chess client

// Function that prints the board when an update is sent to the callback server
type callbackServer struct {
    pb.UnimplementedClientCallbackServer
	boardUpdates chan string
}
func (s *callbackServer) BoardUpdate(ctx context.Context, req *pb.BoardUpdateRequest) (*pb.BoardUpdateResponse, error) {
    fmt.Println("Received board update:")
    fmt.Println(req.Board)
	fmt.Println(req.Message)

    // Sends board update to move loop (non-blocking)
    select {
    case s.boardUpdates <- req.Board:
    default:
        fmt.Println("Board update ignored: move loop not listening")
    }

	if strings.Contains(req.Message, "Checkmate") ||
						strings.Contains(req.Message, "Stalemate") ||
						strings.Contains(req.Message, "forfeited") {
						fmt.Println(req.Message)
						fmt.Println("Game ended.")
						os.Exit(0)
					}

    return &pb.BoardUpdateResponse{Status: "received"}, nil
}

// Callback server that receives requests from the handler
func startCallbackServer(port string, boardUpdates chan string) {
    lis, err := net.Listen("tcp", ":"+port)
    if err != nil {
        log.Fatalf("failed to listen: %v", err)
    }

    grpcServer := grpc.NewServer()
    pb.RegisterClientCallbackServer(grpcServer, &callbackServer{boardUpdates: boardUpdates})
    fmt.Println("Callback server listening on", port)

    if err := grpcServer.Serve(lis); err != nil {
        log.Fatalf("failed to serve: %v", err)
    }
}

func setupForfeitOnInterrupt(handlerClient pb.ChessServiceClient, clientIP string, clientPort int) {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-sigChan
		fmt.Println("\n[!] Interrupted! Sending forfeit...")

		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()

		_, err := handlerClient.Forfeit(ctx, &pb.ForfeitRequest{
			ClientIp:   clientIP,
			ClientPort: int32(clientPort),
		})
		if err != nil {
			fmt.Println("[-] Forfeit RPC failed:", err)
		} else {
			fmt.Println("[✓] Forfeit sent successfully")
		}
		os.Exit(0)
	}()
}

// Returns local IP of the machine/Docker container
func getLocalIP() (string, error) {
	ifaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}

	for _, iface := range ifaces {
		// Skips down or loopbacks interfaces
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue // Skips this interface if it fails
		}
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			if ip == nil || ip.IsLoopback() {
				continue
			}
			// Returns only IPv4
			if ip.To4() != nil {
				return ip.String(), nil
			}
		}
	}
	return "", fmt.Errorf("no connected network interface found")
}

func playGame(client pb.ChessServiceClient, ip string) {
	
	
	player_color := ""

	scanner := bufio.NewScanner(os.Stdin)

	boardUpdates := make(chan string, 1)
	go startCallbackServer("50052",boardUpdates)

	// Sends request to find a game for the client
	req := &pb.FindGameRequest{
		ClientIp:     ip, 
		ClientPort:   50051,
		CallbackUrl:  ip+":50052", 
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	res, err := client.FindGame(ctx, req)
	if err != nil {
		log.Fatalf("FindGame failed: %v", err)
	}

	if res.Status == "no available servers" {
		fmt.Println("No game servers available.")
		return
	}
	player_color = res.Color
	fmt.Printf("✅ Assigned to server: %s:%d as %s\n",
		res.ServerIp, res.ServerPort, res.Color)

	fmt.Printf("\n%s", res.Game)

	setupForfeitOnInterrupt(client, ip, 50051)

	fmt.Print("Enter your move (e.g., e2e4) or 'forfeit': ")
	if !scanner.Scan() {
		return
	}

	done := make(chan struct{})

	go func() {
		for {
			select {
			case <-done:
				return
			default:
				text := strings.TrimSpace(scanner.Text())
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()

				if text == "forfeit" {
					resp, err := client.Forfeit(ctx, &pb.ForfeitRequest{ClientIp: ip, ClientPort: 50051, Color: player_color})
					if err != nil {
						fmt.Println("Request error:", err)
						close(done)
						return
					}
					fmt.Println("Server response:", resp.Message)
					os.Exit(0)
					close(done)
					return
				} else {
					resp, err := client.Move(ctx, &pb.MoveRequest{
						Move: text, ClientIp: ip, ClientPort: 50051, Color: player_color})
					if err != nil {
						fmt.Println("Request error:", err)
						close(done)
						return
					}
					fmt.Println(resp.Game, "\n\n", "Server response:", resp.Status)

					if strings.Contains(resp.Status, "Checkmate") ||
						strings.Contains(resp.Status, "Stalemate") ||
						strings.Contains(resp.Status, "forfeited") {
						fmt.Println("🏁 Game ended.")
						os.Exit(0)
						close(done)
						return
					}
					fmt.Print("Enter your move (e.g., e2e4) or 'forfeit': ")
					if !scanner.Scan() {
						close(done)
						return
					}
				}
			}
		}
	}()


	// Interrupts move input if a board update is received
	for {
		select {
		case <-done:
			return
		case board := <-boardUpdates:
			fmt.Println("\nBoard updated:")
			fmt.Println(board)
		}
	}
}

func main() {
	option := bufio.NewScanner(os.Stdin)
	ip, err := getLocalIP()
	if err != nil {
		fmt.Println("Error:", err)
	} else {
		fmt.Println("Local IP:", ip)
	}
	// Create gRPC client for communication with the Handler
	clientConn, err := grpc.NewClient(
		"dns:///192.168.100.3:50051",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		log.Fatalf("Failed to create gRPC client: %v", err)
	}
	defer clientConn.Close()

	client := pb.NewChessServiceClient(clientConn)
	

	// Makes the player choose the option to find a game or quit the program
	fmt.Print("1 - Find Game \n")
	fmt.Print("2 - Quit \n")
	fmt.Print("Choose an option: ")
	if !option.Scan() {
		os.Exit(0)
	}
	if(option.Text() == "1"){
		playGame(client,ip);
	} else if (option.Text() == "2") {
		os.Exit(0)
	} else {
		fmt.Print("Invalid Input, Try Again!\n")
	}
	
}