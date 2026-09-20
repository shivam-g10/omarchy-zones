// Exercise the real editor state transitions without creating desktop windows
// or invoking Hyprland. All configuration writes are confined to a temp folder.
#define main zones_editor_application_main
#include "../src/editor.cpp"
#undef main

#include <QTemporaryDir>
#include <QTimer>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

QByteArray readFile(const QString& path) {
    QFile file(path);
    require(file.open(QIODevice::ReadOnly), "Cannot read the isolated fixture");
    return file.readAll();
}
} // namespace

int main(int argc, char** argv) {
    try {
        QTemporaryDir isolated;
        require(isolated.isValid(), "Cannot create an isolated test directory");
        qputenv("QT_QPA_PLATFORM", "offscreen");
        qputenv("XDG_CONFIG_HOME", (isolated.path() + "/config").toUtf8());
        qputenv("XDG_DATA_HOME", (isolated.path() + "/data").toUtf8());
        QApplication application(argc, argv);
        auto theme = zones::theme::Theme{};
        theme.activeBorder = {{{0x72f1ffff}, {0xffc857ff}}, 45};
        theme.borderWidth = 3;
        theme.rounding = 12;
        theme.error = 0xf07178ff;
        zones::editorTheme::apply(application, theme);
        require(application.palette().color(QPalette::Mid) == zones::editorTheme::color(theme.muted),
                "The Qt border palette retained an unrelated platform color");
        require(application.palette().color(QPalette::Disabled, QPalette::Text) == zones::editorTheme::color(theme.muted),
                "Disabled controls did not inherit the theme");
        require(application.styleSheet().contains("qlineargradient") && application.styleSheet().contains("border-radius:12px"),
                "Themed controls lost gradient borders or compositor rounding");
        const QByteArray validMonitor = R"json([{"name":"test","width":1000,"height":800,"scale":1,"reserved":[0,0,0,0]}])json";
        QString monitorError;
        require(monitorsFromJson(validMonitor, monitorError).size() == 1, "A valid monitor was rejected");
        require(monitorsFromJson(R"json([{"name":"test","width":1000,"height":800,"scale":0.0000001}])json", monitorError).empty(),
                "Out-of-range logical monitor geometry was accepted");
        require(monitorsFromJson(R"json([{"name":"test","width":1000,"height":800,"scale":1,"reserved":[2147483647,0,2147483647,0]}])json", monitorError).empty(),
                "Overflowing reserved monitor dimensions were accepted");

        const QByteArray original = "omarchy-zones-v1\nDP-test 0 0 500 800\nDP-test 500 0 500 800\n"
                                    "HDMI-test 300 150 1920 1080\nDISCONNECTED 20 20 200 200\n";
        require(QDir().mkpath(QFileInfo(configPath()).absolutePath()), "Cannot create the fixture directory");
        {
            QFile file(configPath());
            require(file.open(QIODevice::WriteOnly) && file.write(original) == original.size(), "Cannot write the legacy fixture");
        }
        const std::vector<Monitor> monitors{{"DP-test", 1000, 800, {0, 0, 1000, 800}, true},
                                            {"HDMI-test", 2560, 1440, {0, 0, 2560, 1414}, false}};
        zones::Profiles initial;
        bool fresh = false, legacy = false;
        QString error;
        require(readSavedProfiles(initial, monitors, fresh, legacy, error), "The editor failed to read v1");
        require(!fresh && legacy && initial.size() == 1 && initial[0].name == "Default", "v1 did not become Default in memory");
        Editor editor(monitors, initial, fresh, legacy);
        editor.show(); application.processEvents();
        auto choice = editor.findChild<QComboBox*>("profileChoice");
        auto display = editor.findChild<QComboBox*>("monitorChoice");
        auto width = editor.findChild<QSpinBox*>("widthValue");
        auto save = editor.findChild<QPushButton*>("saveZones");
        auto canvas = static_cast<Canvas*>(editor.findChild<QWidget*>("zoneCanvas"));
        require(choice && display && width && save && canvas, "The editor controls are unavailable");
        auto geometryHelp = editor.findChild<QLabel*>("geometryHelp");
        require(geometryHelp, "The geometry helper label is unavailable");
        const auto globalRect = [](QWidget* widget) { return QRect(widget->mapToGlobal(QPoint()), widget->size()); };
        const auto numericFields = editor.findChildren<QSpinBox*>();
        for (const auto field : numericFields) {
            require(!globalRect(field).intersects(globalRect(geometryHelp)), "The geometry helper overlaps a numeric field");
            for (const auto other : numericFields)
                if (other != field) require(!globalRect(field).intersects(globalRect(other)), "Numeric rows overlap");
        }
        require(readFile(configPath()) == original, "Opening the editor migrated the file without Save");

        width->setValue(600);
        require(canvas->rectangles->at(0).w == 600 && canvas->rectangles->at(1) == Rect{600, 0, 400, 800},
                "A numeric shared-boundary change did not update both neighbors");
        const auto clickSpinButton = [&](QPointF point) {
            QMouseEvent down(QEvent::MouseButtonPress, point, width->mapToGlobal(point.toPoint()),
                             Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
            QMouseEvent up(QEvent::MouseButtonRelease, point, width->mapToGlobal(point.toPoint()),
                           Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
            QApplication::sendEvent(width, &down);
            QApplication::sendEvent(width, &up);
        };
        clickSpinButton(QPointF(width->width() - 12, 9));
        require(width->value() == 601 && canvas->rectangles->at(1).w == 399,
                "The themed increment arrow lost native spinbox behavior");
        clickSpinButton(QPointF(width->width() - 12, width->height() - 9));
        require(width->value() == 600 && canvas->rectangles->at(1).w == 400,
                "The themed decrement arrow lost native spinbox behavior");

        auto fillProfileDialog = [](QString name, int preset) {
            QTimer::singleShot(0, [name, preset] {
                auto dialog = qobject_cast<QDialog*>(QApplication::activeModalWidget());
                if (!dialog) return;
                auto nameField = dialog->findChild<QLineEdit*>("profileName");
                auto buttons = dialog->findChild<QDialogButtonBox*>();
                if (!nameField || !buttons) { dialog->reject(); return; }
                nameField->setText(name);
                if (preset >= 0) {
                    auto starter = dialog->findChild<QComboBox*>("starterLayout");
                    if (!starter) { dialog->reject(); return; }
                    starter->setCurrentIndex(preset);
                }
                buttons->button(QDialogButtonBox::Ok)->click();
            });
        };
        fillProfileDialog("Focus", 1);
        editor.findChild<QPushButton*>("addProfile")->click();
        require(choice->count() == 2 && choice->currentText() == "Focus", "Creating a profile failed");
        require(*canvas->rectangles == std::vector<Rect>{{125, 88, 750, 624}}, "The Focus starter is not centered at 75% by 78%");
        choice->setCurrentIndex(0);
        require(width->value() == 600, "Switching profiles lost unsaved geometry");
        display->setCurrentIndex(1);
        require(*canvas->rectangles == std::vector<Rect>{{300, 150, 1920, 1080}}, "The existing custom rectangle changed");
        choice->setCurrentIndex(1);
        require(canvas->rectangles->empty(), "A new profile copied an unrequested display layout");
        choice->setCurrentIndex(0); display->setCurrentIndex(0);
        require(width->value() == 600, "Switching displays lost unsaved geometry");

        // Move a real canvas edge in Qt's event system, then cancel. The stable
        // display buffer must roll back both the canvas and the profile model.
        const double scale = std::min((canvas->width() - 48.0) / 1000, (canvas->height() - 78.0) / 800);
        const QPointF origin((canvas->width() - 1000 * scale) / 2, (canvas->height() - 30 - 800 * scale) / 2);
        const QPointF from = origin + QPointF(600 * scale, 400 * scale);
        const QPointF to = from + QPointF(100 * scale, 0);
        QMouseEvent press(QEvent::MouseButtonPress, from, canvas->mapToGlobal(from.toPoint()), Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
        QMouseEvent move(QEvent::MouseMove, to, canvas->mapToGlobal(to.toPoint()), Qt::NoButton, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(canvas, &press); QApplication::sendEvent(canvas, &move);
        require(canvas->rectangles->at(0).w == 700, "The canvas shared boundary did not move");
        canvas->cancel();
        choice->setCurrentIndex(1); choice->setCurrentIndex(0);
        require(canvas->rectangles->at(0).w == 600 && canvas->rectangles->at(1).w == 400,
                "Cancel left stale geometry in a saved profile buffer");

        fillProfileDialog("Default copy", -1);
        editor.findChild<QPushButton*>("duplicateProfile")->click();
        require(choice->count() == 3 && width->value() == 600, "Duplicating a profile lost unsaved edits");
        display->setCurrentIndex(1);
        require(*canvas->rectangles == std::vector<Rect>{{300, 150, 1920, 1080}}, "Duplicating a profile lost another display");
        require(readFile(configPath()) == original, "Editing or switching migrated v1 before explicit Save");

        save->click();
        auto savedBytes = readFile(configPath());
        require(savedBytes.startsWith("omarchy-zones-v2\n"), "Explicit Save did not migrate to v2");
        std::istringstream savedStream(savedBytes.toStdString());
        zones::Profiles saved;
        std::string parseError;
        require(zones::readProfiles(savedStream, saved, parseError), "Saved profiles cannot be read back");
        require(saved.size() == 3 && saved[0].layouts == saved[2].layouts, "Duplicate did not preserve every monitor layout");
        require(saved[0].layouts.at("DISCONNECTED") == initial[0].layouts.at("DISCONNECTED"), "Save dropped a disconnected display");
        require(!save->isEnabled(), "Save did not clear the editor's dirty state");
        require(QDir(QFileInfo(configPath()).absolutePath()).entryList(QDir::Files | QDir::Hidden | QDir::NoDotAndDotDot) == QStringList{"zones.conf"},
                "Save left extra state files instead of definitions only");

        // A blocked destination must retain the old bytes and leave changes
        // unsaved. This exercises QSaveFile's failed-commit path without touching
        // the user's configuration or relying on platform permissions.
        display->setCurrentIndex(0); width->setValue(620);
        const QString retainedPath = isolated.path() + "/retained-zones.conf";
        require(QFile::rename(configPath(), retainedPath), "Cannot prepare the failed-save fixture");
        require(QDir().mkdir(configPath()), "Cannot block the isolated save destination");
        save->click();
        require(readFile(retainedPath) == savedBytes && save->isEnabled(), "A failed save lost the old file or cleared unsaved changes");
        require(QDir().rmdir(configPath()) && QFile::rename(retainedPath, configPath()), "Cannot restore the isolated save fixture");
        save->click();
        require(!save->isEnabled(), "Retrying Save did not recover");
        // Saving through a symlink must never modify its target or pretend the
        // changed profile has been persisted. A retry to the real file works.
        width->setValue(640);
        const QString symlinkTarget = isolated.path() + "/symlink-target.conf";
        const auto beforeSymlink = readFile(configPath());
        require(QFile::rename(configPath(), symlinkTarget), "Cannot prepare the symlink fixture");
        require(QFile::link(symlinkTarget, configPath()), "Cannot create the symlink fixture");
        save->click();
        require(readFile(symlinkTarget) == beforeSymlink && save->isEnabled(),
                "Save through a symlink modified its target or cleared pending changes");
        require(QFile::remove(configPath()) && QFile::rename(symlinkTarget, configPath()), "Cannot restore the symlink fixture");
        save->click();
        require(!save->isEnabled(), "Saving the restored regular file did not recover");
        const auto permissions = QFileInfo(configPath()).permissions();
        require(!(permissions & (QFileDevice::ReadGroup | QFileDevice::WriteGroup | QFileDevice::ReadOther | QFileDevice::WriteOther)),
                "Saved definitions are readable or writable by another account");

        const QString fifoPath = isolated.path() + "/invalid-fifo";
        require(::mkfifo(QFile::encodeName(fifoPath).constData(), 0600) == 0, "Cannot create the FIFO fixture");
        QString inputError;
        require(!readProfileBytes(fifoPath, inputError), "A non-regular profile file was accepted");

        // Saved geometry can exceed a display that became smaller. Dragging an
        // oversized rectangle must fail safely, without an invalid clamp range.
        std::vector<Rect> oversized{{0, 0, 1200, 800}};
        Canvas smallDisplay;
        smallDisplay.resize(600, 440);
        smallDisplay.selectMonitor({"small", 1000, 800, {0, 0, 1000, 800}, true}, oversized);
        const QPointF center(300, 220), moved(330, 240);
        QMouseEvent oversizePress(QEvent::MouseButtonPress, center, center, Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
        QMouseEvent oversizeMove(QEvent::MouseMove, moved, moved, Qt::NoButton, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(&smallDisplay, &oversizePress);
        QApplication::sendEvent(&smallDisplay, &oversizeMove);
        require(oversized == std::vector<Rect>{{0, 0, 1200, 800}}, "Dragging an oversized zone corrupted saved geometry");
        smallDisplay.cancel();

        // A stale UI selection must not index beyond the stable display buffer.
        canvas->selected = 500;
        width->setValue(650);
        editor.findChild<QPushButton*>("deleteZone")->click();
        require(canvas->rectangles->size() == 2, "A stale selection changed the layout");
        std::cout << "Editor profiles, theme palette, monitor bounds, safe selections, FIFO rejection, symlink protection, and atomic private saves passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Editor profile integration failure: " << error.what() << '\n';
        return 1;
    }
}
