#pragma once

#include <QString>
#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QLocalServer>
#include <QLocalSocket>
#include <QObject>
#include <QSet>
#include <QTimer>

#include <cerrno>
#include <fcntl.h>
#include <functional>
#include <memory>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace zones::editorInstance {

// The configuration lock outlives atomic profile saves. Its inode is never
// unlinked: removing a locked file would allow two owners to lock different
// inodes. The kernel releases the lock if the editor exits or crashes.
class Service final : public QObject {
public:
    enum class Result { Primary, Activated, Error };

    explicit Service(QObject* parent = nullptr) : QObject(parent), server_(this) {}
    ~Service() override { release(); }

    Result start(const QString& configurationPath) {
        if (started_) {
            error_ = "The editor instance service has already started.";
            return Result::Error;
        }
        started_ = true;
        if (!preparePaths(configurationPath)) return Result::Error;

        const QByteArray directory = QFile::encodeName(configurationDirectory_);
        const int directoryFd = ::open(directory.constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (directoryFd < 0) return fail("Cannot open the zone configuration directory.");
        lockFd_ = ::openat(directoryFd, ".editor.lock", O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
        ::close(directoryFd);
        struct stat lockStatus{};
        if (lockFd_ < 0 || ::fstat(lockFd_, &lockStatus) != 0 || !S_ISREG(lockStatus.st_mode) ||
            lockStatus.st_uid != ::geteuid() || lockStatus.st_nlink != 1) {
            return fail("Cannot use the editor lock: it must be a regular file owned by your user.");
        }
        if (lockStatus.st_size != 0)
            return fail("Cannot use the editor lock: the existing .editor.lock file is not empty. It was left unchanged.");

        if (::flock(lockFd_, LOCK_EX | LOCK_NB) != 0) {
            const int lockError = errno;
            ::close(lockFd_);
            lockFd_ = -1;
            if (lockError != EWOULDBLOCK && lockError != EAGAIN)
                return fail("Cannot acquire the editor configuration lock.");
            return activateExisting();
        }
        // Recheck after ownership is acquired, before changing permissions. A
        // nonempty file may be unrelated user data and must never be truncated.
        if (::fstat(lockFd_, &lockStatus) != 0 || lockStatus.st_size != 0)
            return fail("Cannot use the editor lock: the existing .editor.lock file is not empty or cannot be inspected. It was left unchanged.");
        if (::fchmod(lockFd_, 0600) != 0)
            return fail("Cannot make the editor lock private.");

        // A socket left by a crashed owner is removable only after acquiring
        // the configuration lock. Never remove an arbitrary filesystem entry.
        const QByteArray endpoint = QFile::encodeName(endpoint_);
        struct stat socketStatus{};
        if (::lstat(endpoint.constData(), &socketStatus) == 0) {
            if (!S_ISSOCK(socketStatus.st_mode) || socketStatus.st_uid != ::geteuid() ||
                ::unlink(endpoint.constData()) != 0)
                return fail("Cannot replace an unsafe editor socket path.");
        } else if (errno != ENOENT) {
            return fail("Cannot inspect the editor socket path.");
        }

        server_.setSocketOptions(QLocalServer::UserAccessOption);
        server_.setMaxPendingConnections(maxClients);
        connect(&server_, &QLocalServer::newConnection, this, [this] { acceptConnections(); });
        if (!server_.listen(endpoint_))
            return fail("Cannot listen for editor activation: " + server_.errorString());
        return Result::Primary;
    }

    const QString& errorString() const { return error_; }

    // Register after constructing the editor. Early requests are coalesced and
    // delivered once the window exists; they never reload its in-memory data.
    void onActivate(std::function<void()> callback) {
        activation_ = std::move(callback);
        if (activationPending_) queueActivation();
    }

private:
    static constexpr int maxClients = 8;
    static constexpr int startupTimeoutMs = 2500;
    static constexpr int clientTimeoutMs = 1500;
    // The primary may spend up to five seconds obtaining monitor information
    // before its Qt event loop can accept connections and return an ACK.
    static constexpr int activationReplyTimeoutMs = 6500;
    static constexpr qsizetype maxCommandBytes = 32;
    inline static const QByteArray activationCommand = "ACTIVATE 1\n";

    QLocalServer server_;
    QSet<QLocalSocket*> clients_;
    QString configurationDirectory_, runtimeDirectory_, endpoint_, error_;
    std::function<void()> activation_;
    int lockFd_ = -1;
    bool started_ = false, activationPending_ = false, activationQueued_ = false;

    void release() {
        // Accepted sockets are QObject children of server_, including sockets
        // already queued for deleteLater(). Destroy them while clients_ still
        // exists; otherwise their disconnected callbacks can run after member
        // destruction has freed that set.
        QObject::disconnect(&server_, nullptr, this, nullptr);
        server_.close();
        const auto sockets = server_.findChildren<QLocalSocket*>(QString(), Qt::FindDirectChildrenOnly);
        for (QLocalSocket* socket : sockets) {
            QObject::disconnect(socket, nullptr, this, nullptr);
            socket->abort();
            delete socket;
        }
        clients_.clear();
        if (lockFd_ >= 0) {
            ::close(lockFd_);
            lockFd_ = -1;
        }
    }

    Result fail(const QString& error) {
        error_ = error;
        release();
        return Result::Error;
    }

    static bool trustedDirectory(const QString& path, bool privateOnly) {
        struct stat status{};
        const QByteArray encoded = QFile::encodeName(path);
        return ::lstat(encoded.constData(), &status) == 0 && S_ISDIR(status.st_mode) &&
            status.st_uid == ::geteuid() && (status.st_mode & (privateOnly ? 0077 : 0022)) == 0;
    }

    bool preparePaths(const QString& configurationPath) {
        const QFileInfo configuration(configurationPath);
        if (configuration.fileName().isEmpty() || configuration.isSymLink()) {
            fail("The zone configuration must have a regular, non-symlink file path.");
            return false;
        }
        if (!QDir().mkpath(configuration.absolutePath())) {
            fail("Cannot create the zone configuration directory.");
            return false;
        }
        configurationDirectory_ = QFileInfo(configuration.absolutePath()).canonicalFilePath();
        if (!trustedDirectory(configurationDirectory_, false)) {
            fail("The zone configuration directory must be owned by your user and not writable by others.");
            return false;
        }

        const QString runtime = QFileInfo(qEnvironmentVariable("XDG_RUNTIME_DIR")).canonicalFilePath();
        if (qEnvironmentVariableIsEmpty("XDG_RUNTIME_DIR") || !trustedDirectory(runtime, true)) {
            fail("XDG_RUNTIME_DIR must identify a private runtime directory owned by your user.");
            return false;
        }
        runtimeDirectory_ = runtime + "/omarchy-zones-editor";
        const QByteArray directory = QFile::encodeName(runtimeDirectory_);
        if ((::mkdir(directory.constData(), 0700) != 0 && errno != EEXIST) ||
            !trustedDirectory(runtimeDirectory_, true)) {
            fail("Cannot create a private editor socket directory.");
            return false;
        }

        // Session scoping prevents a launch on one desktop from activating a
        // window in another. The shared configuration lock still excludes an
        // editor in that other session, including a different runtime directory.
        QByteArray identity = (configurationDirectory_ + '/' + configuration.fileName()).toUtf8();
        for (const char* variable : {"HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY"}) {
            identity += '\0';
            identity += qgetenv(variable);
        }
        const auto digest = QCryptographicHash::hash(identity, QCryptographicHash::Sha256).toHex();
        endpoint_ = runtimeDirectory_ + '/' + QString::fromLatin1(digest.left(32)) + ".sock";
        if (QFile::encodeName(endpoint_).size() >= qsizetype(sizeof(sockaddr_un::sun_path))) {
            fail("The editor runtime socket path is too long.");
            return false;
        }
        return true;
    }

    static bool sameUser(const QLocalSocket& socket) {
        struct ucred credentials{};
        socklen_t size = sizeof(credentials);
        return ::getsockopt(int(socket.socketDescriptor()), SOL_SOCKET, SO_PEERCRED, &credentials, &size) == 0 &&
            size == sizeof(credentials) && credentials.uid == ::geteuid();
    }

    Result activateExisting() {
        // A simultaneous launcher can see the lock before the first process has
        // created its socket. Wait for filesystem events during that bounded
        // startup interval, rather than polling or taking over a live lock.
        QFileSystemWatcher watcher;
        watcher.addPath(runtimeDirectory_);
        QEventLoop changes;
        QTimer deadline;
        deadline.setSingleShot(true);
        connect(&watcher, &QFileSystemWatcher::directoryChanged, &changes, &QEventLoop::quit);
        connect(&deadline, &QTimer::timeout, &changes, &QEventLoop::quit);
        QElapsedTimer elapsed;
        elapsed.start();
        while (elapsed.elapsed() < startupTimeoutMs) {
            QLocalSocket socket;
            socket.setReadBufferSize(maxCommandBytes);
            socket.connectToServer(endpoint_);
            if (socket.waitForConnected(100)) return requestActivation(socket);
            const int remaining = startupTimeoutMs - int(elapsed.elapsed());
            if (remaining <= 0) break;
            deadline.start(remaining);
            changes.exec(QEventLoop::ExcludeUserInputEvents);
            if (!deadline.isActive()) break;
            deadline.stop();
        }
        return fail("The zone editor is already open for this configuration, but is not responding in this desktop session. "
                    "Close that editor before opening another.");
    }

    Result requestActivation(QLocalSocket& socket) {
        if (!sameUser(socket)) return fail("The editor activation socket belongs to another user.");
        if (socket.write(activationCommand) != activationCommand.size())
            return fail("Cannot send the editor activation request.");
        QElapsedTimer elapsed;
        elapsed.start();
        QByteArray reply;
        while (elapsed.elapsed() < activationReplyTimeoutMs && reply.size() < maxCommandBytes) {
            reply += socket.readAll();
            if (reply.contains('\n')) break;
            const int remaining = activationReplyTimeoutMs - int(elapsed.elapsed());
            if (remaining <= 0) break;
            if (!socket.waitForReadyRead(remaining)) {
                reply += socket.readAll();
                break;
            }
        }
        if (reply == "OK\n") return Result::Activated;
        return fail("The zone editor is already running but did not acknowledge activation. No second editor was opened.");
    }

    void acceptConnections() {
        while (server_.hasPendingConnections()) {
            QLocalSocket* socket = server_.nextPendingConnection();
            if (!socket) break;
            if (clients_.size() >= maxClients || !sameUser(*socket)) {
                socket->abort();
                socket->deleteLater();
                continue;
            }
            clients_.insert(socket);
            socket->setReadBufferSize(maxCommandBytes);
            auto* timeout = new QTimer(socket);
            timeout->setSingleShot(true);
            connect(timeout, &QTimer::timeout, socket, &QLocalSocket::abort);
            connect(socket, &QLocalSocket::disconnected, this, [this, socket] {
                clients_.remove(socket);
                socket->deleteLater();
            });
            const auto readRequest = [this, socket, request = std::make_shared<QByteArray>()] {
                *request += socket->readAll();
                if (request->size() > activationCommand.size() || !activationCommand.startsWith(*request)) {
                    socket->abort();
                    return;
                }
                if (*request == activationCommand) {
                    queueActivation();
                    socket->write("OK\n");
                    socket->disconnectFromServer();
                }
            };
            connect(socket, &QLocalSocket::readyRead, this, readRequest);
            timeout->start(clientTimeoutMs);
            // Data can already be buffered when a connection is accepted.
            if (socket->bytesAvailable() > 0) readRequest();
        }
    }

    void queueActivation() {
        activationPending_ = true;
        if (!activation_ || activationQueued_) return;
        activationQueued_ = true;
        QTimer::singleShot(0, this, [this] {
            activationQueued_ = false;
            activationPending_ = false;
            if (activation_) activation_();
        });
    }
};

} // namespace zones::editorInstance
