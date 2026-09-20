// Real subprocesses exercise startup races, activation, and kernel lock
// recovery without opening desktop windows or touching user configuration.
#include "../src/editor_instance.hpp"

#include <QCoreApplication>
#include <QProcess>
#include <QProcessEnvironment>
#include <QPointer>
#include <QSaveFile>
#include <QTemporaryDir>

#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

namespace {
using Service = zones::editorInstance::Service;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void writeFile(const QString& path, const QByteArray& bytes) {
    QFile file(path);
    require(file.open(QIODevice::WriteOnly) && file.write(bytes) == bytes.size(), "Cannot write fixture file");
}

class Worker {
public:
    QProcess process;
    QByteArray output;

    Worker(const QProcessEnvironment& environment, const QString& config, const QStringList& options = {}) {
        process.setProcessEnvironment(environment);
        process.setProcessChannelMode(QProcess::MergedChannels);
        QStringList arguments{"--worker", config};
        arguments += options;
        process.start(QCoreApplication::applicationFilePath(), arguments);
        require(process.waitForStarted(1500), "Cannot start instance-test subprocess");
    }
    ~Worker() {
        if (process.state() != QProcess::NotRunning) {
            process.kill();
            process.waitForFinished(1500);
        }
    }
    bool waitFor(const QByteArray& text, int timeout = 4000) {
        QElapsedTimer elapsed;
        elapsed.start();
        do {
            output += process.readAll();
            if (output.contains(text)) return true;
            if (process.state() == QProcess::NotRunning) return false;
            process.waitForReadyRead(std::max(1, timeout - int(elapsed.elapsed())));
        } while (elapsed.elapsed() < timeout);
        output += process.readAll();
        return output.contains(text);
    }
    void waitExit(int expected) {
        if (process.state() != QProcess::NotRunning)
            require(process.waitForFinished(8000), "A secondary process did not exit promptly");
        output += process.readAll();
        if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != expected) {
            std::cerr << output.toStdString();
            throw std::runtime_error("Unexpected subprocess exit status");
        }
    }
};

QProcessEnvironment environmentFor(const QString& runtime, const QByteArray& session = "test-session") {
    require(QDir().mkpath(runtime), "Cannot create runtime fixture");
    require(QFile::setPermissions(runtime, QFile::ReadOwner | QFile::WriteOwner | QFile::ExeOwner), "Cannot secure runtime fixture");
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert("XDG_RUNTIME_DIR", runtime);
    environment.insert("HYPRLAND_INSTANCE_SIGNATURE", QString::fromLatin1(session));
    environment.insert("WAYLAND_DISPLAY", "wayland-test");
    environment.remove("DISPLAY");
    return environment;
}

QString socketPath(const QString& runtime) {
    const QDir directory(runtime + "/omarchy-zones-editor");
    const auto sockets = directory.entryList({"*.sock"}, QDir::System | QDir::Files);
    require(sockets.size() == 1, "Expected exactly one fixture socket");
    return directory.filePath(sockets.first());
}

void shutdownCheck(const QString& config, bool deferredDelete) {
    QLocalSocket client; // The peer intentionally outlives the service.
    QPointer<QLocalSocket> accepted;
    {
        Service service;
        require(service.start(config) == Service::Result::Primary, "Cannot start shutdown regression service");
        auto* server = service.findChild<QLocalServer*>();
        require(server, "Cannot inspect shutdown regression listener");
        client.connectToServer(server->fullServerName());
        require(client.waitForConnected(1000), "Cannot connect shutdown regression peer");
        QElapsedTimer deadline;
        deadline.start();
        while (deadline.elapsed() < 1000) {
            QCoreApplication::processEvents();
            const auto sockets = server->findChildren<QLocalSocket*>(QString(), Qt::FindDirectChildrenOnly);
            if (!sockets.empty()) {
                accepted = sockets.first();
                break;
            }
        }
        require(accepted && accepted->state() == QLocalSocket::ConnectedState,
                "Shutdown fixture did not accept a live client");
        if (deferredDelete) {
            client.abort();
            deadline.restart();
            while (accepted && accepted->state() != QLocalSocket::UnconnectedState && deadline.elapsed() < 1000)
                QCoreApplication::processEvents();
            // processEvents does not flush DeferredDelete events here. Keep
            // this socket alive until the Service destructor handles it.
            require(accepted && accepted->state() == QLocalSocket::UnconnectedState,
                    "Shutdown fixture did not retain a deferred socket deletion");
        }
    }
    require(accepted.isNull(), "Service shutdown retained an owned IPC socket");
    if (client.state() != QLocalSocket::UnconnectedState)
        client.waitForDisconnected(1000);
    require(client.state() == QLocalSocket::UnconnectedState, "Service shutdown left its peer connected");
    QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    QCoreApplication::processEvents();
}

int worker(QCoreApplication& application, const QStringList& arguments) {
    if (arguments.contains("--shutdown-active") || arguments.contains("--shutdown-deferred")) {
        shutdownCheck(arguments.at(2), arguments.contains("--shutdown-deferred"));
        return 0;
    }
    Service service;
    const auto result = service.start(arguments.at(2));
    if (result == Service::Result::Error) {
        std::cout << "ERROR " << service.errorString().toStdString() << std::endl;
        return 2;
    }
    if (result == Service::Result::Activated) {
        std::cout << "SECONDARY" << std::endl;
        return 0;
    }
    // This value represents unsaved editor data and must remain intact across
    // repeated launch requests. No subprocess reads or reloads the profile file.
    const int unsavedValue = 73;
    service.onActivate([&] {
        std::cout << "ACTIVATED " << unsavedValue << std::endl;
        if (arguments.contains("--quit-on-activate")) application.quit();
    });
    std::cout << "PRIMARY" << std::endl;
    if (arguments.contains("--slow-start")) ::usleep(2200000);
    if (arguments.contains("--unresponsive")) {
        while (true) ::pause();
    }
    QTimer::singleShot(20000, &application, &QCoreApplication::quit);
    return application.exec();
}

void tests() {
    QTemporaryDir fixture("/tmp/ozi-XXXXXX");
    require(fixture.isValid(), "Cannot create isolated instance fixture");
    const QString config = fixture.path() + "/config/zones.conf";
    const QString runtime = fixture.path() + "/r";
    const auto environment = environmentFor(runtime);
    {
        Worker active(environment, fixture.path() + "/shutdown-active/zones.conf", {"--shutdown-active"});
        active.waitExit(0);
        Worker deferred(environment, fixture.path() + "/shutdown-deferred/zones.conf", {"--shutdown-deferred"});
        deferred.waitExit(0);
    }
    std::cout << "PASS shutdown destroys active and deferred IPC clients safely\n";
    auto owner = std::make_unique<Worker>(environment, config);
    require(owner->waitFor("PRIMARY"), "The first launcher did not become owner");
    const QString endpoint = socketPath(runtime);
    struct stat lockStatus{};
    const QByteArray lockPath = QFile::encodeName(QFileInfo(config).absolutePath() + "/.editor.lock");
    require(::lstat(lockPath.constData(), &lockStatus) == 0 && lockStatus.st_size == 0 &&
            (lockStatus.st_mode & 0777) == 0600, "The persistent configuration lock is not empty and private");

    {
        Worker second(environment, config);
        second.waitExit(0);
        require(second.output.contains("SECONDARY"), "Second launch opened another owner");
        require(owner->waitFor("ACTIVATED 73"), "Activation lost the existing owner's unsaved state");
    }
    std::cout << "PASS repeated launch activates the existing process\n";

    {
        QSaveFile file(config);
        require(file.open(QIODevice::WriteOnly) && file.write("new profile") == 11 && file.commit(), "Cannot atomically replace profile fixture");
        Worker second(environment, config);
        second.waitExit(0);
        require(second.output.contains("SECONDARY"), "Atomic profile save invalidated the ownership lock");
        require(QDir().mkpath(fixture.path() + "/alias-parent"), "Cannot create alias fixture");
        require(QFile::link(QFileInfo(config).absolutePath(), fixture.path() + "/alias-parent/config"), "Cannot create configuration directory alias");
        Worker alias(environment, fixture.path() + "/alias-parent/config/zones.conf");
        alias.waitExit(0);
        require(alias.output.contains("SECONDARY"), "Directory alias bypassed the ownership lock");
    }
    std::cout << "PASS atomic saves and directory aliases retain one owner\n";

    {
        Worker independent(environment, fixture.path() + "/other/zones.conf");
        require(independent.waitFor("PRIMARY"), "A separate configuration could not open independently");
    }
    {
        Worker otherSession(environmentFor(runtime, "other-session"), config);
        otherSession.waitExit(2);
        require(otherSession.output.contains("already open"), "Other-session conflict was not explained");
        Worker otherRuntime(environmentFor(fixture.path() + "/r2"), config);
        otherRuntime.waitExit(2);
        require(otherRuntime.output.contains("already open"), "Another runtime bypassed the configuration lock");
    }
    std::cout << "PASS separate configurations work; another session/runtime fails closed\n";

    {
        QLocalSocket fragmented;
        fragmented.connectToServer(endpoint);
        require(fragmented.waitForConnected(1000), "Cannot connect fragmented-request fixture");
        fragmented.write("ACTIVATE ");
        fragmented.waitForBytesWritten(1000);
        // Wait for a bounded lack of response to let the owner consume this
        // prefix before the final bytes arrive in another socket-read event.
        fragmented.waitForReadyRead(40);
        fragmented.write("1\n");
        fragmented.waitForBytesWritten(1000);
        fragmented.waitForReadyRead(1000);
        require(fragmented.readAll() == "OK\n", "A fragmented valid command lost its prefix");
        QLocalSocket invalid;
        invalid.connectToServer(endpoint);
        require(invalid.waitForConnected(1000), "Cannot connect malformed-request fixture");
        invalid.write(QByteArray(512, 'X'));
        invalid.waitForBytesWritten(1000);
        invalid.waitForReadyRead(1500);
        require(invalid.readAll().isEmpty(), "Malformed activation command was acknowledged");
        std::array<std::unique_ptr<QLocalSocket>, 12> stalled;
        for (auto& connection : stalled) {
            connection = std::make_unique<QLocalSocket>();
            connection->connectToServer(endpoint);
            connection->waitForConnected(250);
        }
        for (auto& connection : stalled) {
            if (connection->state() != QLocalSocket::UnconnectedState)
                connection->waitForDisconnected(2500);
        }
        Worker recovery(environment, config);
        recovery.waitExit(0);
        require(recovery.output.contains("SECONDARY"), "Stalled clients exhausted the activation service");
    }
    std::cout << "PASS malformed and stalled clients do not exhaust activation\n";

    owner.reset(); // SIGKILL deliberately leaves a stale endpoint.
    require(QFileInfo::exists(endpoint), "Crash fixture did not leave a stale socket");
    {
        Worker recovered(environment, config);
        require(recovered.waitFor("PRIMARY"), "A crash left the configuration permanently locked");
        Worker secondary(environment, config);
        secondary.waitExit(0);
    }
    std::cout << "PASS crashed owner and stale socket recover\n";

    {
        Worker closing(environment, config, {"--quit-on-activate"});
        require(closing.waitFor("PRIMARY"), "Cannot start orderly shutdown fixture");
        Worker secondary(environment, config);
        secondary.waitExit(0);
        closing.waitExit(0);
        require(!QFileInfo::exists(endpoint), "Clean shutdown left an activation socket behind");
        Worker reopened(environment, config);
        require(reopened.waitFor("PRIMARY"), "Clean shutdown did not release the configuration lock");
    }
    std::cout << "PASS clean shutdown removes its endpoint and permits reopening\n";

    {
        Worker loading(environment, config, {"--slow-start"});
        require(loading.waitFor("PRIMARY"), "Cannot start slow initialization fixture");
        Worker secondary(environment, config);
        secondary.waitExit(0);
        require(secondary.output.contains("SECONDARY") && loading.waitFor("ACTIVATED 73"),
                "A normal initialization delay caused a false activation failure");
    }
    std::cout << "PASS activation waits for a slow primary initialization\n";

    {
        Worker blocked(environment, config, {"--unresponsive"});
        require(blocked.waitFor("PRIMARY"), "Cannot start unresponsive owner fixture");
        Worker secondary(environment, config);
        secondary.waitExit(2);
        require(secondary.output.contains("No second editor"), "Unresponsive owner was replaced unsafely");
    }
    std::cout << "PASS unresponsive owner never creates a duplicate\n";

    {
        std::vector<std::unique_ptr<Worker>> launchers;
        for (int index = 0; index < 8; ++index)
            launchers.push_back(std::make_unique<Worker>(environment, config));
        int owners = 0;
        for (auto& launcher : launchers) {
            require(launcher->waitFor("ARY"), "Concurrent launcher did not report a result");
            if (launcher->output.contains("PRIMARY")) ++owners;
            else {
                launcher->waitExit(0);
                require(launcher->output.contains("SECONDARY"), "Concurrent launch failed to activate owner");
            }
        }
        require(owners == 1, "Simultaneous starts created more than one owner");
    }
    std::cout << "PASS eight simultaneous processes produce exactly one owner\n";

    {
        const QString unsafeConfig = fixture.path() + "/unsafe/zones.conf";
        const QString unsafeLock = fixture.path() + "/unsafe/.editor.lock";
        require(QDir().mkpath(QFileInfo(unsafeConfig).absolutePath()), "Cannot create unsafe-lock fixture");
        writeFile(fixture.path() + "/untouched", "keep");
        require(QFile::link(fixture.path() + "/untouched", unsafeLock), "Cannot create lock symlink fixture");
        Worker symlink(environment, unsafeConfig);
        symlink.waitExit(2);
        QFile unchanged(fixture.path() + "/untouched");
        require(unchanged.open(QIODevice::ReadOnly) && unchanged.readAll() == "keep", "Rejected symlink changed its target");
        require(QFile::remove(unsafeLock), "Cannot clear symlink fixture");
        require(::mkfifo(QFile::encodeName(unsafeLock).constData(), 0600) == 0, "Cannot create FIFO lock fixture");
        Worker fifo(environment, unsafeConfig);
        fifo.waitExit(2);
    }
    std::cout << "PASS symlink and FIFO locks are rejected without blocking\n";

    {
        const QString occupiedConfig = fixture.path() + "/occupied/zones.conf";
        const QString occupiedLock = fixture.path() + "/occupied/.editor.lock";
        const QByteArray original = "This preexisting file belongs to the user.\n";
        require(QDir().mkpath(QFileInfo(occupiedConfig).absolutePath()), "Cannot create nonempty-lock fixture");
        writeFile(occupiedLock, original);
        require(QFile::setPermissions(occupiedLock, QFile::ReadOwner | QFile::WriteOwner | QFile::ReadGroup),
                "Cannot set nonempty-lock fixture permissions");
        struct stat before{}, after{};
        const QByteArray encoded = QFile::encodeName(occupiedLock);
        require(::lstat(encoded.constData(), &before) == 0, "Cannot inspect nonempty-lock fixture");
        Worker occupied(environment, occupiedConfig);
        occupied.waitExit(2);
        require(occupied.output.contains("not empty"), "Nonempty lock rejection did not explain the conflict");
        QFile preserved(occupiedLock);
        require(preserved.open(QIODevice::ReadOnly) && preserved.readAll() == original,
                "A preexisting nonempty lock file was changed");
        require(::lstat(encoded.constData(), &after) == 0 && before.st_dev == after.st_dev &&
                before.st_ino == after.st_ino && before.st_mode == after.st_mode && before.st_size == after.st_size,
                "A rejected nonempty lock file changed identity, permissions, or size");
    }
    std::cout << "PASS nonempty lock conflicts preserve file content, inode, and permissions\n";

    {
        require(QFile::remove(endpoint), "Cannot clear stale socket for unsafe-path fixture");
        writeFile(endpoint, "do not remove");
        Worker unsafeEndpoint(environment, config);
        unsafeEndpoint.waitExit(2);
        QFile untouched(endpoint);
        require(untouched.open(QIODevice::ReadOnly) && untouched.readAll() == "do not remove", "A non-socket endpoint was removed");
        require(QFile::setPermissions(runtime + "/omarchy-zones-editor", QFile::ReadOwner | QFile::WriteOwner |
                                     QFile::ExeOwner | QFile::ReadOther | QFile::WriteOther | QFile::ExeOther),
                "Cannot set unsafe runtime fixture permissions");
        Worker unsafeRuntime(environment, fixture.path() + "/third/zones.conf");
        unsafeRuntime.waitExit(2);
        require(unsafeRuntime.output.contains("private editor socket directory"), "An unsafe runtime socket directory was accepted");
    }
    std::cout << "PASS non-socket endpoints and unsafe socket directories are rejected\n";
}
} // namespace

int main(int argc, char** argv) {
    QCoreApplication application(argc, argv);
    try {
        const auto arguments = application.arguments();
        if (arguments.size() >= 3 && arguments.at(1) == "--worker") return worker(application, arguments);
        tests();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
