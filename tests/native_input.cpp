// Native Linux input injector used only by the manual integration tests.
// It exists for the duration of this process and releases every held key on exit.
#include <linux/input.h>
#include <linux/uinput.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <csignal>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

static volatile sig_atomic_t interrupted = 0;
static void stop(int) { interrupted = 1; }

class Input {
    int fd = -1;
    bool created = false;
    std::set<int> held;
public:
    Input() {
        fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) throw std::runtime_error(std::string("/dev/uinput: ") + strerror(errno));
        auto enable = [this](unsigned long request, int value) {
            if (ioctl(fd, request, value) < 0)
                throw std::runtime_error(std::string("uinput ioctl: ") + strerror(errno));
        };
        enable(UI_SET_EVBIT, EV_KEY);
        enable(UI_SET_EVBIT, EV_REL);
        enable(UI_SET_RELBIT, REL_X);
        enable(UI_SET_RELBIT, REL_Y);
        for (int key = 1; key < KEY_MAX; ++key) enable(UI_SET_KEYBIT, key);
        uinput_setup setup{};
        setup.id.bustype = BUS_USB;
        setup.id.vendor = 0x1;
        setup.id.product = 0x1;
        snprintf(setup.name, sizeof(setup.name), "Omarchy Zones integration test input");
        if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0)
            throw std::runtime_error(std::string("create uinput: ") + strerror(errno));
        created = true;
        std::this_thread::sleep_for(std::chrono::milliseconds(650));
    }
    ~Input() {
        if (fd < 0) return;
        for (int key : held) raw(EV_KEY, key, 0);
        raw(EV_SYN, SYN_REPORT, 0);
        if (created) ioctl(fd, UI_DEV_DESTROY);
        close(fd);
    }
    void raw(int type, int code, int value) noexcept {
        input_event event{};
        event.type = type;
        event.code = code;
        event.value = value;
        (void)write(fd, &event, sizeof(event));
    }
    void key(int code, bool down) {
        if (down) held.insert(code); else held.erase(code);
        raw(EV_KEY, code, down ? 1 : 0);
        raw(EV_SYN, SYN_REPORT, 0);
    }
    void move(int dx, int dy) {
        raw(EV_REL, REL_X, dx);
        raw(EV_REL, REL_Y, dy);
        raw(EV_SYN, SYN_REPORT, 0);
    }
};

static int keyCode(const std::string& name) {
    static const std::map<std::string, int> codes = {
        {"KEY_LEFTSHIFT", KEY_LEFTSHIFT}, {"KEY_RIGHTSHIFT", KEY_RIGHTSHIFT},
        {"KEY_LEFTCTRL", KEY_LEFTCTRL}, {"KEY_RIGHTCTRL", KEY_RIGHTCTRL},
        {"KEY_LEFTALT", KEY_LEFTALT}, {"KEY_RIGHTALT", KEY_RIGHTALT},
        {"KEY_LEFTMETA", KEY_LEFTMETA}, {"KEY_RIGHTMETA", KEY_RIGHTMETA},
        {"KEY_ESC", KEY_ESC}, {"KEY_ENTER", KEY_ENTER}, {"KEY_TAB", KEY_TAB},
        {"BTN_LEFT", BTN_LEFT}, {"BTN_RIGHT", BTN_RIGHT}, {"BTN_MIDDLE", BTN_MIDDLE}
    };
    auto it = codes.find(name);
    if (it != codes.end()) return it->second;
    std::size_t length;
    int code = std::stoi(name, &length);
    if (length != name.size() || code <= 0 || code >= KEY_MAX)
        throw std::runtime_error("Unknown key: " + name);
    return code;
}

int main(int argc, char**) {
    if (argc > 1) {
        std::cout << "Read commands from stdin; this helper injects real desktop input.\n"
            "key KEY_LEFTCTRL down|up\nbutton BTN_LEFT down|up\n"
            "move DX DY [STEPS=1] [INTERVAL_MS=16]\nsleep MILLISECONDS\nquit\n"
            "Numeric Linux input key codes are also accepted. All held keys release on exit.\n";
        return 0;
    }
    signal(SIGINT, stop);
    signal(SIGTERM, stop);
    try {
        Input input;
        std::cerr << "READY\n" << std::flush;
        std::string pending;
        while (!interrupted) {
            pollfd item{STDIN_FILENO, POLLIN, 0};
            int result = poll(&item, 1, -1);
            if (result < 0) { if (errno == EINTR) continue; break; }
            char buffer[4096];
            ssize_t count = read(STDIN_FILENO, buffer, sizeof(buffer));
            if (count <= 0) break;
            pending.append(buffer, count);
            std::size_t newline;
            while ((newline = pending.find('\n')) != std::string::npos && !interrupted) {
                std::string line = pending.substr(0, newline);
                pending.erase(0, newline + 1);
                std::istringstream stream(line);
                std::string command;
                stream >> command;
                if (command.empty() || command[0] == '#') continue;
                if (command == "quit") return 0;
                if (command == "key" || command == "button") {
                    std::string name, state;
                    stream >> name >> state;
                    if (state != "down" && state != "up") throw std::runtime_error("Expected down or up");
                    input.key(keyCode(name), state == "down");
                } else if (command == "move") {
                    int dx, dy, steps = 1, interval = 16;
                    if (!(stream >> dx >> dy)) throw std::runtime_error("Expected move DX DY");
                    stream >> steps >> interval;
                    if (steps < 1 || steps > 10000 || interval < 0 || interval > 1000)
                        throw std::runtime_error("Invalid motion timing");
                    int emittedX = 0, emittedY = 0;
                    for (int i = 1; i <= steps && !interrupted; ++i) {
                        const int x = dx * i / steps, y = dy * i / steps;
                        input.move(x - emittedX, y - emittedY);
                        emittedX = x; emittedY = y;
                        std::this_thread::sleep_for(std::chrono::milliseconds(interval));
                    }
                } else if (command == "sleep") {
                    int ms;
                    if (!(stream >> ms) || ms < 0 || ms > 60000) throw std::runtime_error("Invalid sleep");
                    for (; ms > 0 && !interrupted; ms -= 10)
                        std::this_thread::sleep_for(std::chrono::milliseconds(std::min(ms, 10)));
                } else throw std::runtime_error("Unknown command: " + command);
                std::cerr << "OK " << line << '\n' << std::flush;
            }
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
