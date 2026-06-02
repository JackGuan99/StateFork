#include <unistd.h>
#include <iostream>
#include <unordered_map>
#include <fstream>
#include <thread>
#include <mutex>
#include <chrono>
#include <random>
#include <atomic>
#include <csignal>

using namespace std;

/**
 * Simple multi-threaded in-memory Random Database (RDB) with metadata logging.
 */

unordered_map<int, string> db;
mutex db_mutex;
atomic<bool> running(true);

void signal_handler(int signum) {
    running = false;
}

#include <fstream>

string get_memory_usage_kb() {
    ifstream status_file("/proc/self/status");
    string line;
    while (getline(status_file, line)) {
        if (line.find("VmRSS:") == 0) {  // VmRSS: Resident Set Size
            return line;
        }
    }
    return "VmRSS: Unknown";
}

// Generate random alphanumeric string of given length
string random_string(size_t length) {
    static const string chars =
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789";
    static thread_local mt19937 rng(random_device{}());
    static thread_local uniform_int_distribution<> dist(0, chars.size() - 1);

    string result;
    result.reserve(length);
    for (size_t i = 0; i < length; ++i) {
        result += chars[dist(rng)];
    }
    return result;
}

// Logging thread
void log_metadata() {
    ofstream log_file("/tmp/db_log.txt", ios::app);
    while (running) {
        {
            lock_guard<mutex> lock(db_mutex);
            time_t now = chrono::system_clock::to_time_t(chrono::system_clock::now());
            string timestamp = ctime(&now);
            timestamp.pop_back(); // Remove newline character
            log_file << timestamp
                     << " | DB size: " << db.size()
                     << " | " << get_memory_usage_kb() << endl;
            log_file.flush();
        }
        this_thread::sleep_for(chrono::seconds(2));
    }
}

// Worker thread: insert large string values
void update_db() {
    mt19937 rng(random_device{}());
    uniform_int_distribution<int> key_dist(1, 1000000000);
    const size_t value_size = 2048; // 2 KB

    while (running) {
        int key = key_dist(rng);
        string value = random_string(value_size);

        {
            lock_guard<mutex> lock(db_mutex);
            db[key] = value;
        }
        this_thread::sleep_for(chrono::milliseconds(5));
    }
}

int main() {
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    thread logger(log_metadata);
    thread db_updater(update_db);

    cout << "PID: " << getpid() 
         << " [Main = " << this_thread::get_id() 
         << ", Logger = " << logger.get_id() 
         << ", DB = " << db_updater.get_id() << "]" << endl;

    logger.join();
    db_updater.join();

    return 0;
}

