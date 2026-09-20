#include "geometry.hpp"
#include "profiles.hpp"
#include "editor_theme.hpp"
#include "editor_instance.hpp"
#include "editor_activation.hpp"

#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QDir>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFile>
#include <QFormLayout>
#include <QGridLayout>
#include <QFrame>
#include <QHBoxLayout>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMainWindow>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPainter>
#include <QProcess>
#include <QPointer>
#include <QPixmap>
#include <QPushButton>
#include <QSaveFile>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QShortcut>
#include <QSpinBox>
#include <QStandardPaths>
#include <QVBoxLayout>

#include <array>
#include <cmath>
#include <functional>
#include <map>
#include <optional>
#include <sstream>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
using zones::Rect;
struct Monitor { QString name; int width, height; Rect usable; bool focused; };

QString configPath() {
    return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + "/omarchy-zones/zones.conf";
}
std::vector<Monitor> monitorsFromJson(const QByteArray& bytes, QString& error) {
    QJsonParseError jsonError;
    if (bytes.size() > 1024 * 1024) { error = "Hyprland returned too much monitor information."; return {}; }
    const auto document = QJsonDocument::fromJson(bytes, &jsonError);
    if (jsonError.error != QJsonParseError::NoError || !document.isArray()) {
        error = "Hyprland returned invalid monitor information.";
        return {};
    }
    std::vector<Monitor> monitors;
    for (const auto& value : document.array()) {
        const auto object = value.toObject();
        if (object["disabled"].toBool()) continue;
        const auto name = object["name"].toString();
        double scale = object["scale"].toDouble(1);
        if (!std::isfinite(scale) || scale <= 0) continue;
        const double logicalWidth = object["width"].toDouble() / scale;
        const double logicalHeight = object["height"].toDouble() / scale;
        // Keep every pixel coordinate representable by both the editor fields
        // and the validated profile format, including after a monitor change.
        if (!std::isfinite(logicalWidth) || !std::isfinite(logicalHeight) ||
            logicalWidth < 1 || logicalHeight < 1 || logicalWidth > 32768 || logicalHeight > 32768) continue;
        int width = int(std::lround(logicalWidth));
        int height = int(std::lround(logicalHeight));
        if (object["transform"].toInt() % 2) std::swap(width, height);
        const auto reserved = object["reserved"].toArray();
        int left = reserved.size() == 4 ? reserved[0].toInt() : 0;
        int top = reserved.size() == 4 ? reserved[1].toInt() : 0;
        int right = reserved.size() == 4 ? reserved[2].toInt() : 0;
        int bottom = reserved.size() == 4 ? reserved[3].toInt() : 0;
        if (name.isEmpty() || left < 0 || top < 0 || right < 0 || bottom < 0 ||
            int64_t(left) + right >= width || int64_t(top) + bottom >= height) continue;
        Rect usable{left, top, width - left - right, height - top - bottom};
        if (usable.w >= 64 && usable.h >= 32)
            monitors.push_back({name, width, height, usable, object["focused"].toBool()});
    }
    if (monitors.empty()) error = "No active monitor has enough usable space for zones.";
    return monitors;
}

std::vector<Monitor> readMonitors(QString& error) {
    QProcess command;
    command.start("hyprctl", {"-j", "monitors"});
    if (!command.waitForFinished(4000) || command.exitStatus() != QProcess::NormalExit || command.exitCode() != 0) {
        if (command.state() != QProcess::NotRunning) {
            command.kill();
            command.waitForFinished(1000);
        }
        error = "Cannot read Hyprland monitors. Open the editor inside your Hyprland session.";
        return {};
    }
    return monitorsFromJson(command.readAllStandardOutput(), error);
}

std::optional<std::string> readProfileBytes(const QString& path, QString& error) {
    // Open nonblocking before checking the descriptor: a FIFO or a path swap
    // must not turn opening the editor into an unbounded wait.
    const int descriptor = ::open(QFile::encodeName(path).constData(), O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (descriptor < 0) {
        error = "Cannot read " + path + ". Your saved zones were not changed.";
        return {};
    }
    struct OwnedDescriptor {
        int value;
        ~OwnedDescriptor() { ::close(value); }
    } owned{descriptor};
    struct stat metadata{};
    if (::fstat(descriptor, &metadata) != 0 || !S_ISREG(metadata.st_mode)) {
        error = "The zone configuration must be a regular file.";
        return {};
    }
    if (metadata.st_size < 0 || uint64_t(metadata.st_size) > zones::maxProfileFileBytes) {
        error = "The zone file is too large.";
        return {};
    }
    std::string contents;
    contents.reserve(size_t(metadata.st_size));
    std::array<char, 4096> buffer;
    while (true) {
        const auto count = ::read(descriptor, buffer.data(), buffer.size());
        if (count == 0) return contents;
        if (count < 0) {
            if (errno == EINTR) continue;
            error = "Cannot finish reading the zone configuration.";
            return {};
        }
        if (size_t(count) > zones::maxProfileFileBytes - contents.size()) {
            error = "The zone file is too large.";
            return {};
        }
        contents.append(buffer.data(), size_t(count));
    }
}

bool readSavedProfiles(zones::Profiles& profiles, const std::vector<Monitor>& monitors,
                       bool& fresh, bool& legacy, QString& error) {
    QFile file(configPath());
    fresh = !file.exists();
    legacy = false;
    if (fresh) {
        zones::Profile profile{"Default", {}};
        for (const auto& monitor : monitors) {
            auto r = monitor.usable;
            int half = r.w / 2;
            profile.layouts[monitor.name.toStdString()] = {{r.x, r.y, half, r.h}, {r.x + half, r.y, r.w - half, r.h}};
        }
        profiles.push_back(std::move(profile));
        return true;
    }
    const auto contents = readProfileBytes(configPath(), error);
    if (!contents) return false;
    std::istringstream stream(*contents);
    std::string parseError;
    if (zones::readProfiles(stream, profiles, parseError, &legacy)) return true;
    error = QString::fromStdString(parseError);
    return false;
}

class Canvas : public QWidget {
public:
    std::vector<Rect>* rectangles = nullptr;
    Monitor monitor{};
    int selected = -1;
    bool drawing = false;
    std::function<void()> onSelection, onChange;
    std::function<void(QString)> onStatus;

    explicit Canvas(QWidget* parent = nullptr) : QWidget(parent) {
        setMouseTracking(true);
        setObjectName("zoneCanvas");
        setMinimumSize(560, 360);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
        setFocusPolicy(Qt::StrongFocus);
        setAccessibleName("Zone layout canvas");
        setToolTip("Drag an edge to resize adjacent zones together. Drag inside a zone to move it.");
    }
    void cancel() {
        if (drag != Drag::None && rectangles) { *rectangles = before; if (onChange) onChange(); }
        drag = Drag::None; drawing = false; preview.reset(); unsetCursor(); update();
    }
    void selectMonitor(const Monitor& value, std::vector<Rect>& valueRectangles) {
        drag = Drag::None; preview.reset(); drawing = false;
        monitor = value; rectangles = &valueRectangles;
        selected = rectangles->empty() ? -1 : 0; update();
    }

    bool hasSelection() const {
        return rectangles && selected >= 0 && size_t(selected) < rectangles->size();
    }

protected:
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing);
        const auto display = screenRect();
        const auto& theme = zones::editorTheme::current();
        painter.setPen(theme.borderWidth > 0
                           ? QPen(zones::editorTheme::gradientBrush(theme.inactiveBorder, display), theme.borderWidth)
                           : QPen(Qt::NoPen));
        painter.setBrush(palette().base());
        painter.drawRoundedRect(display, theme.rounding, theme.rounding);
        auto muted = palette().color(QPalette::PlaceholderText);
        muted.setAlpha(45);
        painter.setPen(QPen(muted, 1, Qt::DotLine));
        painter.drawRect(toScreen(monitor.usable));
        QColor accent = palette().color(QPalette::Highlight);
        if (rectangles) for (size_t i = 0; i < rectangles->size(); ++i) {
            const double inset = std::max(1.0, theme.borderWidth / 2);
            QRectF rectangle = toScreen((*rectangles)[i]).adjusted(inset, inset, -inset, -inset);
            QColor fill = zones::editorTheme::withAlpha(theme.accent, int(i) == selected ? theme.selected.fillAlpha : theme.normal.fillAlpha);
            painter.setBrush(fill);
            painter.setPen(theme.borderWidth > 0
                               ? QPen(zones::editorTheme::gradientBrush(int(i) == selected ? theme.activeBorder : theme.inactiveBorder, rectangle), theme.borderWidth)
                               : QPen(Qt::NoPen));
            painter.drawRoundedRect(rectangle, theme.rounding, theme.rounding);
            painter.setPen(palette().color(QPalette::Text));
            QFont title = font(); title.setPixelSize(qRound(theme.fontSize * 1.25)); title.setBold(true); painter.setFont(title);
            painter.drawText(rectangle.adjusted(8, 6, -8, -6), Qt::AlignCenter, QString::number(i + 1));
            if (rectangle.width() > 105 && rectangle.height() > 95) {
                painter.setFont(font());
                const auto& r = (*rectangles)[i];
                painter.setPen(palette().color(QPalette::PlaceholderText));
                painter.drawText(rectangle.adjusted(8, 44, -8, -8), Qt::AlignCenter,
                                 QString("%1 × %2").arg(r.w).arg(r.h));
            }
            if (int(i) == selected) {
                painter.setPen(Qt::NoPen); painter.setBrush(accent);
                for (auto point : {QPointF(rectangle.left(), rectangle.center().y()), QPointF(rectangle.right(), rectangle.center().y()),
                                   QPointF(rectangle.center().x(), rectangle.top()), QPointF(rectangle.center().x(), rectangle.bottom())})
                    painter.drawEllipse(point, 3.5, 3.5);
            }
        }
        if (preview && rectangles) {
            auto proposed = *rectangles; proposed.push_back(*preview);
            QColor color = zones::valid(proposed, monitor.usable) ? accent : zones::editorTheme::color(theme.error);
            painter.setPen(QPen(color, 2, Qt::DashLine)); color.setAlpha(30); painter.setBrush(color);
            painter.drawRect(toScreen(*preview));
        }
        painter.setPen(palette().color(QPalette::PlaceholderText)); painter.setFont(font());
        painter.drawText(QRectF(display.left(), display.bottom() + 9, display.width(), 24), Qt::AlignCenter,
                         QString("%1  ·  %2 × %3 logical pixels").arg(monitor.name).arg(monitor.width).arg(monitor.height));
    }

    void mousePressEvent(QMouseEvent* event) override {
        if (event->button() != Qt::LeftButton || !rectangles) return;
        setFocus(); press = toLogical(event->position()); before = *rectangles;
        if (drawing) {
            press.setX(int(std::clamp<int64_t>(press.x(), monitor.usable.x, monitor.usable.right())));
            press.setY(int(std::clamp<int64_t>(press.y(), monitor.usable.y, monitor.usable.bottom())));
            drag = Drag::Draw; preview = Rect{press.x(), press.y(), 0, 0};
        } else if (auto hit = edgeAt(event->position())) {
            selected = hit->first; edge = hit->second; drag = Drag::Edge;
            if (onSelection) onSelection();
        } else {
            selected = -1;
            for (size_t i = 0; i < rectangles->size(); ++i) {
                if (toScreen((*rectangles)[i]).contains(event->position())) { selected = int(i); break; }
            }
            drag = selected < 0 ? Drag::None : Drag::Move;
            if (onSelection) onSelection();
        }
        update();
    }

    void mouseMoveEvent(QMouseEvent* event) override {
        if (!rectangles) return;
        auto point = toLogical(event->position());
        if (drag == Drag::None) {
            if (drawing) setCursor(Qt::CrossCursor);
            else if (auto hit = edgeAt(event->position()))
                setCursor(hit->second == zones::Edge::Left || hit->second == zones::Edge::Right ? Qt::SizeHorCursor : Qt::SizeVerCursor);
            else unsetCursor();
            return;
        }
        if (drag == Drag::Draw) {
            point.setX(int(std::clamp<int64_t>(point.x(), monitor.usable.x, monitor.usable.right())));
            point.setY(int(std::clamp<int64_t>(point.y(), monitor.usable.y, monitor.usable.bottom())));
            preview = Rect{std::min(point.x(), press.x()), std::min(point.y(), press.y()),
                           std::abs(point.x() - press.x()), std::abs(point.y() - press.y())};
            update(); return;
        }
        if (selected < 0 || size_t(selected) >= before.size()) {
            cancel();
            return;
        }
        auto proposed = before;
        bool accepted = false;
        if (drag == Drag::Edge) {
            const auto& original = before[selected];
            int64_t coordinate = edge == zones::Edge::Left ? original.x : edge == zones::Edge::Right ? original.right()
                : edge == zones::Edge::Top ? original.y : original.bottom();
            const bool vertical = edge == zones::Edge::Left || edge == zones::Edge::Right;
            coordinate += vertical ? int64_t(point.x()) - press.x() : int64_t(point.y()) - press.y();
            accepted = zones::moveBoundary(proposed, selected, edge, coordinate, monitor.usable);
        } else {
            const auto& original = before[selected];
            // An old saved zone can exceed a newly smaller monitor. In that
            // case clamp's lower bound would exceed its upper bound. Reject
            // movement while still allowing edge resizing or deletion.
            if (original.w <= monitor.usable.w && original.h <= monitor.usable.h) {
                const int x = int(std::clamp<int64_t>(int64_t(original.x) + point.x() - press.x(),
                                                     monitor.usable.x, monitor.usable.right() - original.w));
                const int y = int(std::clamp<int64_t>(int64_t(original.y) + point.y() - press.y(),
                                                     monitor.usable.y, monitor.usable.bottom() - original.h));
                accepted = zones::move(proposed, selected, x, y, monitor.usable);
            }
        }
        if (accepted) {
            if (*rectangles != proposed) { *rectangles = std::move(proposed); if (onChange) onChange(); }
        } else if (onStatus) onStatus("That change would overlap zones or exceed the usable screen.");
        update();
    }

    void mouseReleaseEvent(QMouseEvent* event) override {
        if (event->button() != Qt::LeftButton) return;
        if (drag == Drag::Draw && preview && rectangles) {
            auto proposed = *rectangles; proposed.push_back(*preview);
            if (zones::valid(proposed, monitor.usable)) {
                *rectangles = std::move(proposed); selected = int(rectangles->size()) - 1;
                if (onChange) onChange();
            } else if (onStatus) onStatus("Draw in free space. Minimum zone size: 32 × 32 pixels.");
            preview.reset(); drawing = false;
            if (onSelection) onSelection();
        }
        drag = Drag::None; unsetCursor(); update();
    }

private:
    enum class Drag { None, Draw, Edge, Move };
    Drag drag = Drag::None;
    zones::Edge edge = zones::Edge::Right;
    QPoint press;
    std::vector<Rect> before;
    std::optional<Rect> preview;
    QRectF screenRect() const {
        if (monitor.width <= 0 || monitor.height <= 0) return {};
        const double scale = std::max(0.001, std::min((width() - 48.0) / monitor.width, (height() - 78.0) / monitor.height));
        const QSizeF size(monitor.width * scale, monitor.height * scale);
        return {(width() - size.width()) / 2, (height() - 30 - size.height()) / 2, size.width(), size.height()};
    }
    QRectF toScreen(const Rect& r) const {
        const auto display = screenRect();
        if (display.isEmpty() || monitor.width <= 0) return {};
        const auto scale = display.width() / monitor.width;
        return {display.x() + r.x * scale, display.y() + r.y * scale, r.w * scale, r.h * scale};
    }
    QPoint toLogical(QPointF point) const {
        const auto display = screenRect();
        if (display.isEmpty() || monitor.width <= 0) return {};
        const auto scale = display.width() / monitor.width;
        const auto coordinate = [scale](double offset) {
            if (!std::isfinite(offset)) return 0;
            return int(std::lround(std::clamp(offset / scale, -65536.0, 65536.0)));
        };
        return {coordinate(point.x() - display.x()), coordinate(point.y() - display.y())};
    }
    std::optional<std::pair<int, zones::Edge>> edgeAt(QPointF point) const {
        if (!rectangles) return {};
        auto test = [&](int index) -> std::optional<std::pair<int, zones::Edge>> {
            const auto r = toScreen((*rectangles)[index]); constexpr double tolerance = 7;
            if (point.y() >= r.top() && point.y() <= r.bottom()) {
                if (std::abs(point.x() - r.left()) < tolerance) return {{index, zones::Edge::Left}};
                if (std::abs(point.x() - r.right()) < tolerance) return {{index, zones::Edge::Right}};
            }
            if (point.x() >= r.left() && point.x() <= r.right()) {
                if (std::abs(point.y() - r.top()) < tolerance) return {{index, zones::Edge::Top}};
                if (std::abs(point.y() - r.bottom()) < tolerance) return {{index, zones::Edge::Bottom}};
            }
            return {};
        };
        if (hasSelection()) if (auto hit = test(selected)) return hit;
        for (size_t i = 0; i < rectangles->size(); ++i) if (auto hit = test(int(i))) return hit;
        return {};
    }
};

class Editor : public QMainWindow {
public:
    Editor(std::vector<Monitor> values, zones::Profiles definitions, bool fresh, bool legacy)
        : monitors(std::move(values)), profiles(std::move(definitions)), savedProfiles(profiles),
          dirty(fresh), unsavedFile(fresh), legacyFile(legacy) {
        setWindowTitle("Omarchy Zones"); resize(1160, 740); setMinimumSize(990, 640);
        auto central = new QWidget; setCentralWidget(central);
        auto root = new QVBoxLayout(central); root->setSizeConstraint(QLayout::SetMinimumSize); root->setContentsMargins(24, 20, 24, 20); root->setSpacing(16);
        auto top = new QHBoxLayout;
        auto title = new QLabel("Zones"); title->setObjectName("editorTitle"); QFont titleFont = font(); titleFont.setPixelSize(qRound(zones::editorTheme::current().fontSize * 2)); titleFont.setBold(true); title->setFont(titleFont);
        top->addWidget(title); top->addStretch();
        monitorChoice = new zones::editorTheme::ComboBox; monitorChoice->setAccessibleName("Monitor"); monitorChoice->setObjectName("monitorChoice");
        for (const auto& m : monitors) monitorChoice->addItem(m.name);
        top->addWidget(new QLabel("Display")); top->addWidget(monitorChoice); root->addLayout(top);
        auto profileRow = new QHBoxLayout;
        profileRow->addWidget(new QLabel("Profile"));
        profileChoice = new zones::editorTheme::ComboBox; profileChoice->setObjectName("profileChoice"); profileChoice->setAccessibleName("Profile");
        profileChoice->setMinimumWidth(230); profileChoice->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
        profileChoice->setMinimumContentsLength(18); profileChoice->setIconSize(QSize(48, 28));
        profileRow->addWidget(profileChoice, 1);
        addProfile = new QPushButton("New profile"); addProfile->setObjectName("addProfile"); profileRow->addWidget(addProfile);
        duplicateProfile = new QPushButton("Duplicate"); duplicateProfile->setObjectName("duplicateProfile"); profileRow->addWidget(duplicateProfile);
        auto rename = new QPushButton("Rename"); rename->setObjectName("renameProfile"); profileRow->addWidget(rename);
        removeProfile = new QPushButton("Delete profile"); removeProfile->setObjectName("deleteProfile"); profileRow->addWidget(removeProfile);
        root->addLayout(profileRow);
        auto intro = new QLabel("Save different layouts. Choose one from the picker when dragging a window."); intro->setProperty("role", "muted"); root->addWidget(intro);

        auto body = new QHBoxLayout; body->setSpacing(20);
        canvas = new Canvas; body->addWidget(canvas, 1);
        auto panelWidget = new QWidget;
        auto panel = new QVBoxLayout(panelWidget); panel->setContentsMargins(0, 0, 0, 0); panel->setSpacing(12);
        panel->setSizeConstraint(QLayout::SetMinAndMaxSize);
        selectedLabel = new QLabel("Zone 1"); auto bold = font(); bold.setBold(true); selectedLabel->setFont(bold); panel->addWidget(selectedLabel);
        fieldsPanel = new QWidget;
        auto form = new QGridLayout(fieldsPanel); form->setContentsMargins(0, 0, 0, 0); form->setSpacing(10);
        form->setSizeConstraint(QLayout::SetMinimumSize);
        const std::array<QString, 4> labels{"X", "Y", "Width", "Height"};
        for (int i = 0; i < 4; ++i) {
            fields[i] = new zones::editorTheme::SpinBox; fields[i]->setRange(i < 2 ? 0 : 32, 32768); fields[i]->setSuffix(" px");
            fields[i]->setKeyboardTracking(false); fields[i]->setAccessibleName(labels[i]);
            fields[i]->setObjectName(labels[i].toLower() + "Value");
            form->addWidget(new QLabel(labels[i]), i, 0);
            form->addWidget(fields[i], i, 1);
            connect(fields[i], &QSpinBox::valueChanged, this, [this, i](int value) { editValue(i, value); });
        }
        panel->addWidget(fieldsPanel);
        auto note = new QLabel("X / Y move a zone.\nWidth / Height move shared edges."); note->setObjectName("geometryHelp"); note->setWordWrap(true); note->setProperty("role", "muted"); panel->addWidget(note);
        auto divider = new QFrame; divider->setFrameShape(QFrame::HLine); panel->addWidget(divider);
        draw = new QPushButton("Draw zone"); draw->setObjectName("drawZone"); draw->setCheckable(true); panel->addWidget(draw);
        connect(draw, &QPushButton::clicked, this, [this](bool enabled) {
            if (enabled && zoneCount() >= int(zones::maxZonesPerProfile)) { draw->setChecked(false); status("At most 64 zones are allowed per profile."); return; }
            canvas->drawing = enabled; canvas->setCursor(enabled ? Qt::CrossCursor : Qt::ArrowCursor);
            status(enabled ? "Drag a rectangle in free space. Escape cancels." : "Drag edges, move zones, or enter exact values.");
        });
        splitVertical = new QPushButton("Split left / right"); splitVertical->setObjectName("splitVertical"); panel->addWidget(splitVertical);
        splitHorizontal = new QPushButton("Split top / bottom"); splitHorizontal->setObjectName("splitHorizontal"); panel->addWidget(splitHorizontal);
        remove = new QPushButton("Delete zone"); remove->setObjectName("deleteZone"); panel->addWidget(remove);
        connect(splitVertical, &QPushButton::clicked, this, [this] { split(true); });
        connect(splitHorizontal, &QPushButton::clicked, this, [this] { split(false); });
        connect(remove, &QPushButton::clicked, this, [this] { deleteSelected(); });
        panel->addStretch();
        auto help = new QLabel("Edits only change zone definitions.\nExisting windows stay where they are."); help->setWordWrap(true); help->setProperty("role", "muted"); help->setMaximumWidth(235); panel->addWidget(help);
        // Font/theme changes can make the controls taller than the available
        // editor area. Preserve their intrinsic sizes and scroll the sidebar.
        auto sidebar = new QScrollArea;
        sidebar->setWidgetResizable(true);
        sidebar->setFrameShape(QFrame::NoFrame);
        sidebar->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        sidebar->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
        sidebar->setMinimumWidth(255);
        sidebar->setMaximumWidth(300);
        sidebar->setWidget(panelWidget);
        body->addWidget(sidebar); root->addLayout(body, 1);

        statusLabel = new QLabel; statusLabel->setTextFormat(Qt::PlainText); statusLabel->setWordWrap(true); statusLabel->setMinimumHeight(38); root->addWidget(statusLabel);
        auto footer = new QHBoxLayout; savedLabel = new QLabel; footer->addWidget(savedLabel); footer->addStretch();
        auto close = new QPushButton("Close"); footer->addWidget(close); connect(close, &QPushButton::clicked, this, &QWidget::close);
        save = new QPushButton("Save profiles"); save->setObjectName("saveZones"); save->setDefault(true); footer->addWidget(save); root->addLayout(footer);
        connect(save, &QPushButton::clicked, this, [this] { saveZones(); });
        auto shortcut = new QShortcut(QKeySequence::Save, this); connect(shortcut, &QShortcut::activated, this, [this] { saveZones(); });
        auto escape = new QShortcut(QKeySequence(Qt::Key_Escape), this); connect(escape, &QShortcut::activated, this, [this] { canvas->cancel(); draw->setChecked(false); refresh(); });
        auto deletion = new QShortcut(QKeySequence(Qt::Key_Delete), canvas); deletion->setContext(Qt::WidgetShortcut);
        connect(deletion, &QShortcut::activated, this, [this] { deleteSelected(); });
        canvas->onChange = [this] { recordLayoutChange(); };
        canvas->onSelection = [this] { draw->setChecked(canvas->drawing); refresh(); };
        canvas->onStatus = [this](QString text) { status(std::move(text)); };
        connect(monitorChoice, &QComboBox::currentIndexChanged, this, [this](int index) { changeMonitor(index); });
        connect(profileChoice, &QComboBox::currentIndexChanged, this, [this](int index) { changeProfile(index); });
        connect(addProfile, &QPushButton::clicked, this, [this] { createProfile(); });
        connect(duplicateProfile, &QPushButton::clicked, this, [this] { copyProfile(); });
        connect(rename, &QPushButton::clicked, this, [this] { renameCurrentProfile(); });
        connect(removeProfile, &QPushButton::clicked, this, [this] { deleteCurrentProfile(); });
        int focused = 0;
        for (size_t i = 0; i < monitors.size(); ++i) if (monitors[i].focused) focused = int(i);
        rebuildProfileChoices(); monitorChoice->setCurrentIndex(focused); changeMonitor(focused);
    }

    void refreshTheme() {
        if (auto title = findChild<QLabel*>("editorTitle")) {
            auto titleFont = title->font();
            titleFont.setPixelSize(qRound(zones::editorTheme::current().fontSize * 2));
            title->setFont(titleFont);
        }
        for (auto field : fields) field->updateGeometry();
        fieldsPanel->layout()->invalidate();
        fieldsPanel->updateGeometry();
        centralWidget()->layout()->invalidate();
        rebuildProfileChoices();
        canvas->update();
    }

protected:
    void showEvent(QShowEvent* event) override {
        QMainWindow::showEvent(event);
        // Child style sheets and font metrics are polished by this point.
        // Recalculate numeric row heights before the first visible frame.
        refreshTheme();
    }

    void closeEvent(QCloseEvent* event) override {
        if (!dirty) { event->accept(); return; }
        auto answer = QMessageBox::question(this, "Unsaved profiles", "Save your profile changes before closing?",
                                             QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel, QMessageBox::Save);
        if (answer == QMessageBox::Cancel || (answer == QMessageBox::Save && !saveZones())) event->ignore();
        else event->accept();
    }

private:
    std::vector<Monitor> monitors;
    zones::Profiles profiles, savedProfiles;
    // The canvas always points at this stable buffer. Adding or deleting a
    // profile cannot invalidate its pointer into a reallocated profile vector.
    std::vector<Rect> displayRectangles;
    int currentProfile = 0;
    bool dirty, unsavedFile, legacyFile, refreshing = false;
    Canvas* canvas;
    QComboBox *monitorChoice, *profileChoice;
    std::array<QSpinBox*, 4> fields;
    QWidget* fieldsPanel;
    QLabel *selectedLabel, *statusLabel, *savedLabel;
    QPushButton *draw, *splitVertical, *splitHorizontal, *remove, *save;
    QPushButton *addProfile, *duplicateProfile, *removeProfile;

    int zoneCount() const {
        int count = 0;
        for (const auto& [name, rectangles] : profiles[currentProfile].layouts) count += int(rectangles.size());
        return count;
    }
    void status(QString text) { statusLabel->setText(std::move(text)); }
    void markChanges() { dirty = unsavedFile || profiles != savedProfiles; }
    void recordLayoutChange() {
        const auto monitorName = canvas->monitor.name.toStdString();
        auto& layouts = profiles[currentProfile].layouts;
        if (displayRectangles.empty()) layouts.erase(monitorName);
        else layouts[monitorName] = displayRectangles;
        markChanges(); refresh();
    }
    QIcon layoutIcon(const std::vector<Rect>& rectangles, const Monitor& monitor, QSize size = {48, 28}) const {
        const qreal ratio = devicePixelRatioF();
        QPixmap image(QSize(qCeil(size.width() * ratio), qCeil(size.height() * ratio)));
        image.setDevicePixelRatio(ratio);
        image.fill(Qt::transparent);
        QPainter painter(&image); painter.setRenderHint(QPainter::Antialiasing);
        const auto accent = palette().color(QPalette::Highlight);
        painter.setPen(QPen(palette().color(QPalette::PlaceholderText), 1));
        painter.setBrush(palette().base()); painter.drawRoundedRect(QRectF(0.5, 0.5, size.width() - 1, size.height() - 1), 3, 3);
        const double scale = std::min((size.width() - 6.0) / monitor.width, (size.height() - 6.0) / monitor.height);
        const QPointF origin((size.width() - monitor.width * scale) / 2, (size.height() - monitor.height * scale) / 2);
        QColor fill = accent; fill.setAlpha(55); painter.setBrush(fill);
        painter.setPen(QPen(zones::editorTheme::gradientBrush(zones::editorTheme::current().activeBorder, QRectF(QPointF(), size)), 1));
        for (const auto& r : rectangles)
            painter.drawRect(QRectF(origin.x() + r.x * scale, origin.y() + r.y * scale, r.w * scale, r.h * scale).adjusted(0.5, 0.5, -0.5, -0.5));
        return QIcon(image);
    }
    QIcon profileIcon(const zones::Profile& profile) const {
        const auto& monitor = monitors[std::max(0, monitorChoice->currentIndex())];
        const auto found = profile.layouts.find(monitor.name.toStdString());
        return layoutIcon(found == profile.layouts.end() ? std::vector<Rect>{} : found->second, monitor);
    }
    void rebuildProfileChoices() {
        QSignalBlocker blocker(profileChoice);
        profileChoice->clear();
        for (const auto& profile : profiles) profileChoice->addItem(profileIcon(profile), QString::fromStdString(profile.name));
        profileChoice->setCurrentIndex(currentProfile);
    }
    void changeProfile(int index) {
        if (index < 0 || index >= int(profiles.size()) || index == currentProfile) return;
        canvas->cancel();
        currentProfile = index;
        changeMonitor(monitorChoice->currentIndex());
    }
    void changeMonitor(int index) {
        if (index < 0 || index >= int(monitors.size())) return;
        canvas->cancel();
        const auto& layouts = profiles[currentProfile].layouts;
        const auto found = layouts.find(monitors[index].name.toStdString());
        displayRectangles = found == layouts.end() ? std::vector<Rect>{} : found->second;
        canvas->selectMonitor(monitors[index], displayRectangles); draw->setChecked(false);
        rebuildProfileChoices(); refresh();
    }
    void refresh() {
        refreshing = true;
        bool hasSelection = canvas->hasSelection();
        selectedLabel->setText(hasSelection ? QString("Zone %1").arg(canvas->selected + 1) : "Select a zone");
        for (auto field : fields) field->setEnabled(hasSelection);
        remove->setEnabled(hasSelection);
        splitVertical->setEnabled(hasSelection && zoneCount() < int(zones::maxZonesPerProfile));
        splitHorizontal->setEnabled(hasSelection && zoneCount() < int(zones::maxZonesPerProfile));
        draw->setEnabled(zoneCount() < int(zones::maxZonesPerProfile));
        if (hasSelection) {
            const auto& r = (*canvas->rectangles)[canvas->selected];
            for (int i = 0; i < 4; ++i) fields[i]->setValue(std::array<int, 4>{r.x, r.y, r.w, r.h}[i]);
            splitVertical->setEnabled(r.w >= 64 && zoneCount() < int(zones::maxZonesPerProfile));
            splitHorizontal->setEnabled(r.h >= 64 && zoneCount() < int(zones::maxZonesPerProfile));
        }
        addProfile->setEnabled(profiles.size() < zones::maxProfiles);
        duplicateProfile->setEnabled(profiles.size() < zones::maxProfiles);
        removeProfile->setEnabled(profiles.size() > 1);
        savedLabel->setText(dirty ? "Unsaved changes" : QString("%1 saved %2").arg(profiles.size()).arg(profiles.size() == 1 ? "profile" : "profiles"));
        save->setEnabled(dirty || legacyFile);
        if (currentProfile < profileChoice->count()) profileChoice->setItemIcon(currentProfile, profileIcon(profiles[currentProfile]));
        bool invalid = canvas->rectangles && !zones::valid(*canvas->rectangles, canvas->monitor.usable);
        status(invalid ? "Display bounds changed. Adjust or delete zones outside the usable screen before saving."
                       : "Drag shared edges to resize. Use Draw zone or Split to add zones.");
        refreshing = false; canvas->update();
    }
    std::vector<Rect> starterLayout(int choice) const {
        const auto r = monitors[monitorChoice->currentIndex()].usable;
        if (choice == 0) return {};
        if (choice == 1) {
            const int width = std::max(zones::minimumExtent, r.w * 75 / 100);
            const int height = std::max(zones::minimumExtent, r.h * 78 / 100);
            return {{r.x + (r.w - width) / 2, r.y + (r.h - height) / 2, width, height}};
        }
        const int columns = choice == 4 ? 3 : 2;
        std::vector<Rect> rectangles;
        for (int i = 0; i < columns; ++i) {
            const int start = choice == 3 ? (i == 0 ? 0 : r.w * 2 / 3) : r.w * i / columns;
            const int end = choice == 3 ? (i == 0 ? r.w * 2 / 3 : r.w) : r.w * (i + 1) / columns;
            rectangles.push_back({r.x + start, r.y, end - start, r.h});
        }
        return rectangles;
    }
    QString availableName(QString base) const {
        auto exists = [&](const QString& name) {
            return std::ranges::any_of(profiles, [&](const auto& profile) { return profile.name == name.toStdString(); });
        };
        // Leave room for the suffix even when duplicating a long UTF-8 name.
        while (base.toUtf8().size() > 48) base.chop(1);
        QString name = base;
        for (int number = 2; exists(name); ++number) name = base + " " + QString::number(number);
        return name;
    }
    std::optional<std::pair<std::string, int>> profileDialog(const QString& title, const QString& initial,
                                                           bool withStarter, bool replacing = false) {
        canvas->cancel(); draw->setChecked(false);
        QDialog dialog(this); dialog.setWindowTitle(title); dialog.setMinimumWidth(410);
        auto layout = new QVBoxLayout(&dialog); layout->setSpacing(16);
        auto form = new QFormLayout;
        auto name = new QLineEdit(initial); name->setObjectName("profileName"); name->setAccessibleName("Profile name");
        name->setMaxLength(int(zones::maxProfileNameBytes)); form->addRow("Name", name);
        QComboBox* starter = nullptr;
        if (withStarter) {
            starter = new zones::editorTheme::ComboBox; starter->setObjectName("starterLayout"); starter->setAccessibleName("Starter layout");
            starter->setIconSize(QSize(64, 36));
            const QStringList choices{"Empty", "Focus", "Split", "Main + side", "Three columns"};
            for (int i = 0; i < choices.size(); ++i)
                starter->addItem(layoutIcon(starterLayout(i), monitors[monitorChoice->currentIndex()], {64, 36}), choices[i]);
            starter->setCurrentIndex(2); form->addRow("Start with", starter);
        }
        layout->addLayout(form);
        if (withStarter) {
            auto help = new QLabel("The starter layout applies to " + monitors[monitorChoice->currentIndex()].name + ". Other displays start empty.");
            help->setTextFormat(Qt::PlainText); help->setWordWrap(true); layout->addWidget(help);
        }
        auto errorLabel = new QLabel; errorLabel->setTextFormat(Qt::PlainText); errorLabel->setProperty("role", "error"); errorLabel->setWordWrap(true); errorLabel->setObjectName("profileNameError"); layout->addWidget(errorLabel);
        auto buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel); layout->addWidget(buttons);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, [&] {
            auto candidate = profiles;
            auto candidateName = name->text().trimmed().toStdString();
            if (replacing) candidate[currentProfile].name = candidateName;
            else candidate.push_back({candidateName, {}});
            std::string error;
            if (!zones::validateProfiles(candidate, error)) { errorLabel->setText(QString::fromStdString(error)); name->setFocus(); return; }
            if (starter && !zones::valid(starterLayout(starter->currentIndex()), monitors[monitorChoice->currentIndex()].usable)) {
                errorLabel->setText("This display is too small for that starter layout. Choose another."); return;
            }
            dialog.accept();
        });
        name->selectAll(); name->setFocus();
        if (dialog.exec() != QDialog::Accepted) return {};
        return std::pair{name->text().trimmed().toStdString(), starter ? starter->currentIndex() : 0};
    }
    void createProfile() {
        if (profiles.size() >= zones::maxProfiles) return;
        auto result = profileDialog("New profile", availableName("Profile"), true);
        if (!result) return;
        zones::Profile profile{result->first, {}};
        auto rectangles = starterLayout(result->second);
        if (!rectangles.empty()) profile.layouts[monitors[monitorChoice->currentIndex()].name.toStdString()] = std::move(rectangles);
        profiles.push_back(std::move(profile)); currentProfile = int(profiles.size()) - 1;
        markChanges(); rebuildProfileChoices(); changeMonitor(monitorChoice->currentIndex());
    }
    void copyProfile() {
        if (profiles.size() >= zones::maxProfiles) return;
        auto initial = availableName(QString::fromStdString(profiles[currentProfile].name) + " copy");
        auto result = profileDialog("Duplicate profile", initial, false);
        if (!result) return;
        auto copy = profiles[currentProfile]; copy.name = result->first;
        profiles.push_back(std::move(copy)); currentProfile = int(profiles.size()) - 1;
        markChanges(); rebuildProfileChoices(); changeMonitor(monitorChoice->currentIndex());
    }
    void renameCurrentProfile() {
        auto result = profileDialog("Rename profile", QString::fromStdString(profiles[currentProfile].name), false, true);
        if (!result) return;
        profiles[currentProfile].name = result->first; markChanges(); rebuildProfileChoices(); refresh();
    }
    void deleteCurrentProfile() {
        if (profiles.size() <= 1) return;
        canvas->cancel();
        if (zoneCount() > 0) {
            QMessageBox question(QMessageBox::Question, "Delete profile",
                                 "Delete “" + QString::fromStdString(profiles[currentProfile].name) +
                                     "” and its zone definitions? Existing windows will stay unchanged.",
                                 QMessageBox::Yes | QMessageBox::Cancel, this);
            question.setTextFormat(Qt::PlainText);
            question.setDefaultButton(QMessageBox::Cancel);
            if (question.exec() != QMessageBox::Yes) return;
        }
        profiles.erase(profiles.begin() + currentProfile);
        currentProfile = std::min(currentProfile, int(profiles.size()) - 1);
        markChanges(); rebuildProfileChoices(); changeMonitor(monitorChoice->currentIndex());
    }
    void editValue(int field, int value) {
        if (refreshing || !canvas->hasSelection() || field < 0 || field >= int(fields.size())) return;
        auto& rectangles = *canvas->rectangles;
        const auto original = rectangles[canvas->selected];
        bool accepted = false;
        switch (field) {
            case 0:
                accepted = zones::move(rectangles, canvas->selected, value, original.y, canvas->monitor.usable);
                break;
            case 1:
                accepted = zones::move(rectangles, canvas->selected, original.x, value, canvas->monitor.usable);
                break;
            case 2:
                accepted = zones::moveBoundary(rectangles, canvas->selected, zones::Edge::Right,
                                               int64_t(original.x) + value, canvas->monitor.usable);
                break;
            case 3:
                accepted = zones::moveBoundary(rectangles, canvas->selected, zones::Edge::Bottom,
                                               int64_t(original.y) + value, canvas->monitor.usable);
                break;
        }
        if (accepted) {
            recordLayoutChange();
        } else {
            refresh();
            status("Value rejected: zones cannot overlap, exceed the usable screen, or be smaller than 32 × 32.");
        }
    }

    void split(bool vertical) {
        if (!canvas->hasSelection() || zoneCount() >= int(zones::maxZonesPerProfile)) return;
        auto& rectangles = *canvas->rectangles;
        auto first = rectangles[canvas->selected], second = first;
        if (vertical) { first.w /= 2; second.x += first.w; second.w -= first.w; }
        else { first.h /= 2; second.y += first.h; second.h -= first.h; }
        if (first.w < 32 || first.h < 32 || second.w < 32 || second.h < 32) return;
        rectangles[canvas->selected] = first; rectangles.push_back(second); recordLayoutChange();
    }
    void deleteSelected() {
        if (!canvas->hasSelection()) return;
        auto& rectangles = *canvas->rectangles;
        rectangles.erase(rectangles.begin() + canvas->selected);
        canvas->selected = rectangles.empty() ? -1 : std::min(canvas->selected, int(rectangles.size()) - 1);
        recordLayoutChange();
    }
    bool saveZones() {
        // Saving writes definitions only. It never dispatches window movement
        // or stores a window identifier.
        for (const auto& profile : profiles) {
            for (const auto& monitor : monitors) {
                const auto found = profile.layouts.find(monitor.name.toStdString());
                if (found != profile.layouts.end() && !zones::valid(found->second, monitor.usable)) {
                    status("Cannot save “" + QString::fromStdString(profile.name) + "”: zones on " + monitor.name + " overlap or exceed the usable screen."); return false;
                }
            }
        }
        std::ostringstream output;
        std::string error;
        if (!zones::writeProfiles(output, profiles, error)) { status(QString::fromStdString(error)); return false; }
        const auto contents = output.str();
        const QString path = configPath();
        if (!QDir().mkpath(QFileInfo(path).absolutePath())) { status("Cannot create the zone configuration directory."); return false; }
        if (QFileInfo(path).isSymLink()) {
            status("Cannot save profiles through a symbolic link. Replace it with a regular zone file first.");
            return false;
        }
        QSaveFile file(path);
        file.setDirectWriteFallback(false);
        if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) { status("Cannot write profiles: " + file.errorString()); return false; }
        if (!file.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner)) {
            status("Cannot make the zone configuration private: " + file.errorString());
            return false;
        }
        if (file.write(contents.data(), qint64(contents.size())) != qint64(contents.size()) || !file.commit()) {
            status("Cannot save profiles: " + file.errorString()); return false;
        }
        savedProfiles = profiles; dirty = false; unsavedFile = false; legacyFile = false;
        refresh(); status("Profiles saved. Existing windows are unchanged."); return true;
    }

};
} // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    app.setApplicationName("Omarchy Zones");
    app.setApplicationVersion("0.3.1");
    app.setDesktopFileName("omarchy-zones-editor");
    zones::editorInstance::Service instance;
    const auto launch = instance.start(configPath());
    if (launch == zones::editorInstance::Service::Result::Activated) return 0;
    if (launch == zones::editorInstance::Service::Result::Error) {
        QMessageBox::critical(nullptr, "Omarchy Zones", instance.errorString());
        return 1;
    }
    zones::editorTheme::Controller themeController(app);
    QString error;
    auto monitors = readMonitors(error);
    if (monitors.empty()) { QMessageBox::critical(nullptr, "Omarchy Zones", error); return 1; }
    zones::Profiles profiles; bool fresh, legacy;
    if (!readSavedProfiles(profiles, monitors, fresh, legacy, error)) { QMessageBox::critical(nullptr, "Omarchy Zones", error); return 1; }
    Editor editor(std::move(monitors), std::move(profiles), fresh, legacy);
    zones::editorInstance::Activation activation(editor);
    instance.onActivate([guard = QPointer<zones::editorInstance::Activation>(&activation)] {
        if (guard) guard->request();
    });
    themeController.onChanged = [guard = QPointer<Editor>(&editor)] {
        if (guard) guard->refreshTheme();
    };
    editor.show();
    return app.exec();
}
