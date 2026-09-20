#pragma once

#include <QApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QProcess>
#include <QRegularExpression>
#include <QTimer>
#include <QWidget>
#include <QWindow>
#include <limits>

namespace zones::editorInstance {

// Explicit relaunches should reveal this editor, including its active dialog.
// Wayland may reject an activation request without a fresh input serial. On
// Hyprland, resolve the active dialog within our process and focus its exact
// address. A PID-only selector can pick a parent blocked by that modal dialog.
class Activation final : public QObject {
public:
    explicit Activation(QWidget& editor) : QObject(&editor), window(&editor) {
        deadline.setSingleShot(true);
        connect(&deadline, &QTimer::timeout, this, [this] { command.kill(); });
        connect(&command, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
            deadline.stop();
            if (querying && code == 0 && status == QProcess::NormalExit) focusTarget();
            else querying = false;
        });
        connect(&command, &QProcess::errorOccurred, this, [this] { deadline.stop(); });
        connect(&command, &QProcess::readyReadStandardOutput, this, [this] {
            output += command.readAllStandardOutput();
            if (output.size() > 1024 * 1024) command.kill();
        });
        command.setStandardErrorFile(QProcess::nullDevice());
    }

    ~Activation() override {
        if (command.state() != QProcess::NotRunning) {
            command.kill();
            command.waitForFinished(1000);
        }
    }

    void request() {
        if (!window) return;
        QWidget* target = QApplication::activeModalWidget();
        if (!target) target = window;
        if (target->isMinimized()) target->showNormal();
        else target->show();
        target->raise();
        target->activateWindow();
        if (target->windowHandle()) target->windowHandle()->requestActivate();

        if (qEnvironmentVariableIsEmpty("HYPRLAND_INSTANCE_SIGNATURE") ||
            QGuiApplication::platformName() != "wayland" ||
            command.state() != QProcess::NotRunning) return;
        requestedWindow = target;
        output.clear();
        querying = true;
        command.start("hyprctl", {"-j", "clients"});
        deadline.start(1500);
    }

private:
    QPointer<QWidget> window;
    QPointer<QWidget> requestedWindow;
    QProcess command;
    QTimer deadline;
    QByteArray output;
    bool querying = false;

    void focusTarget() {
        querying = false;
        output += command.readAllStandardOutput();
        if (!requestedWindow || !requestedWindow->isVisible() || output.size() > 1024 * 1024) return;
        QWidget* target = QApplication::activeModalWidget();
        if (!target) target = window;
        if (target != requestedWindow) return;
        const auto document = QJsonDocument::fromJson(output);
        if (!document.isArray()) return;
        QString address;
        int nearestHistory = std::numeric_limits<int>::max();
        for (const auto& value : document.array()) {
            const auto client = value.toObject();
            if (client["pid"].toInteger() != QCoreApplication::applicationPid() ||
                client["title"].toString() != target->windowTitle() || !client["mapped"].toBool()) continue;
            const auto candidate = client["address"].toString();
            static const QRegularExpression validAddress("^0x[0-9a-fA-F]+$");
            if (!validAddress.match(candidate).hasMatch()) continue;
            // Qt's critical dialogs can share the main window's title. The
            // active modal is the most recently focused matching surface.
            const int history = client["focusHistoryID"].toInt(-1);
            if (address.isEmpty() || (history >= 0 && history < nearestHistory)) {
                address = candidate;
                if (history >= 0) nearestHistory = history;
            }
        }
        if (address.isEmpty()) return;
        output.clear();
        command.start("hyprctl", {"eval", QString("hl.dispatch(hl.dsp.focus({window=\"address:%1\"}))").arg(address)});
        deadline.start(1500);
    }
};

} // namespace zones::editorInstance
