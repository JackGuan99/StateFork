#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <signal.h>

#define SOCKET_PATH "/tmp/test_socket"
#define LOG_PATH "/tmp/uds_test.log"
#define MAX_RETRIES 3
#define RETRY_DELAY 2
#define COMM_INTERVAL 20

void log_message(const char* process_name, const char* message) {
    FILE* log_file = fopen(LOG_PATH, "a");
    if (log_file == NULL) {
        fprintf(stderr, "Failed to open log file: %s\n", strerror(errno));
        return;
    }
    
    time_t now;
    time(&now);
    char* time_str = ctime(&now);
    time_str[strlen(time_str) - 1] = '\0'; // Remove newline
    
    fprintf(log_file, "[%s] %s\t %s\n", time_str, process_name, message);
    fflush(log_file);
    fclose(log_file);
}

void cleanup_socket() {
    unlink(SOCKET_PATH);
}

void signal_handler(int sig) {
    log_message("SIGNAL", "Received termination signal...");
    // cleanup_socket();
    exit(0);
}

// Borrowed and adapted from my 4118 OS's example code

void sender_process() {
    int sock;
    struct sockaddr_un addr;
    int counter = 1;
    int retries = 0;
    char buffer[256];
    
    log_message("SENDER", "Starting sender process");
    
    // Create socket once at startup
    sock = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (sock == -1) {
        snprintf(buffer, sizeof(buffer), "Failed to create socket: %s", strerror(errno));
        log_message("SENDER", buffer);
        exit(1);
    }
    
    // Set up destination address
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);
    
    log_message("SENDER", "Socket created, starting communication");
    
    // Main communication loop - keep using the same socket
    while (1) {
        // Generate and log the value to be sent
        snprintf(buffer, sizeof(buffer), "Generated counter value: %d", counter);
        log_message("SENDER", buffer);
        
        // Wait before sending for easier concurrency observation
        sleep(5);
        
        // Send the counter value using the persistent socket
        snprintf(buffer, sizeof(buffer), "%d", counter);
        if (sendto(sock, buffer, strlen(buffer), 0, (struct sockaddr*)&addr, sizeof(addr)) == -1) {
            snprintf(buffer, sizeof(buffer), "Failed to send data: %s", strerror(errno));
            log_message("SENDER", buffer);
            
            retries++;
            if (retries >= MAX_RETRIES) {
                log_message("SENDER", "Max retries reached, exiting");
                close(sock);
                exit(1);
            }
            
            snprintf(buffer, sizeof(buffer), "Retrying send (attempt %d/%d)", retries, MAX_RETRIES);
            log_message("SENDER", buffer);
            sleep(RETRY_DELAY);
            continue;
        }
        
        // Reset retry counter on successful send
        if (retries > 0) {
            log_message("SENDER", "Send operation recovered successfully");
            retries = 0;
        }
        
        snprintf(buffer, sizeof(buffer), "Sent counter value: %d", counter);
        log_message("SENDER", buffer);
        
        counter++;
        
        // Wait for next communication cycle
        sleep(COMM_INTERVAL - 5);
    }
    
    close(sock);
}

void receiver_process() {
    int sock;
    struct sockaddr_un addr;
    char buffer[256];
    int retries = 0;
    
    log_message("RECEIVER", "Starting receiver process");
    
    // Clean up any existing socket file
    cleanup_socket();
    
    // Create socket once at startup
    sock = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (sock == -1) {
        snprintf(buffer, sizeof(buffer), "Failed to create socket: %s", strerror(errno));
        log_message("RECEIVER", buffer);
        exit(1);
    }
    
    // Set up address
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCKET_PATH, sizeof(addr.sun_path) - 1);
    
    // Bind socket
    if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) == -1) {
        snprintf(buffer, sizeof(buffer), "Failed to bind socket: %s", strerror(errno));
        log_message("RECEIVER", buffer);
        close(sock);
        exit(1);
    }
    
    log_message("RECEIVER", "Socket bound, ready to receive data");
    
    // Main communication loop - keep using the same socket
    while (1) {
        // Receive data using the persistent socket
        ssize_t bytes_received = recv(sock, buffer, sizeof(buffer) - 1, 0);
        if (bytes_received == -1) {
            snprintf(buffer, sizeof(buffer), "Failed to receive data: %s", strerror(errno));
            log_message("RECEIVER", buffer);
            
            retries++;
            if (retries >= MAX_RETRIES) {
                log_message("RECEIVER", "Max retries reached, exiting");
                close(sock);
                exit(1);
            }
            
            snprintf(buffer, sizeof(buffer), "Retrying receive (attempt %d/%d)", retries, MAX_RETRIES);
            log_message("RECEIVER", buffer);
            sleep(RETRY_DELAY);
            continue;
        }
        
        // Reset retry counter on successful receive
        if (retries > 0) {
            log_message("RECEIVER", "Receive operation recovered successfully");
            retries = 0;
        }
        
        // Null-terminate the received data
        buffer[bytes_received] = '\0';

        sleep(1); // Simulate processing delay
        
        // Log received value
        char log_buffer[512];
        snprintf(log_buffer, sizeof(log_buffer), "Received counter value: %s", buffer);
        log_message("RECEIVER", log_buffer);
    }
    
    close(sock);
}

int main() {
    pid_t sender_pid, receiver_pid;
    int status;
    char buffer[256];
    
    // Set up signal handlers for cleanup
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Initialize log file
    snprintf(buffer, sizeof(buffer), "Parent process (PID: %d) starting test", getpid());
    log_message("PARENT", buffer);
    printf("UDS >> %s\n", buffer);
    
    // Fork receiver process first
    receiver_pid = fork();
    if (receiver_pid == -1) {
        log_message("PARENT", "Failed to fork receiver process");
        exit(1);
    } else if (receiver_pid == 0) {
        // Child process - receiver
        receiver_process();
        exit(0);
    }
    
    snprintf(buffer, sizeof(buffer), "Forked receiver process (PID: %d)", receiver_pid);
    log_message("PARENT", buffer);
    
    // Give receiver time to set up socket and bind
    sleep(2);
    
    // Fork sender process
    sender_pid = fork();
    if (sender_pid == -1) {
        log_message("PARENT", "Failed to fork sender process");
        kill(receiver_pid, SIGTERM);
        exit(1);
    } else if (sender_pid == 0) {
        // Child process - sender
        sender_process();
        exit(0);
    }
    
    snprintf(buffer, sizeof(buffer), "Forked sender process (PID: %d)", sender_pid);
    log_message("PARENT", buffer);
    
    log_message("PARENT", "Both child processes started with persistent DGRAM sockets");
    
    // Wait for child processes
    while (1) {
        pid_t finished_pid = waitpid(-1, &status, WNOHANG);
        
        if (finished_pid > 0) {
            if (finished_pid == sender_pid) {
                snprintf(buffer, sizeof(buffer), "Sender process (PID: %d) terminated", sender_pid);
                log_message("PARENT", buffer);
                kill(receiver_pid, SIGTERM);
                break;
            } else if (finished_pid == receiver_pid) {
                snprintf(buffer, sizeof(buffer), "Receiver process (PID: %d) terminated", receiver_pid);
                log_message("PARENT", buffer);
                kill(sender_pid, SIGTERM);
                break;
            }
        } else if (finished_pid == -1 && errno != ECHILD) {
            snprintf(buffer, sizeof(buffer), "waitpid error: %s", strerror(errno));
            log_message("PARENT", buffer);
        }
        
        sleep(1);
    }
    
    // Wait for remaining child process to terminate
    wait(NULL);
    
    log_message("PARENT", "All child processes terminated, cleaning up");
    // cleanup_socket();
    
    return 0;
}