#pragma once

#include "theme.hpp"

#include <QApplication>
#include <QColor>
#include <QComboBox>
#include <QAbstractItemView>
#include <QAbstractButton>
#include <QLineEdit>
#include <QListView>
#include <QPushButton>
#include <QPainterPath>
#include <QResizeEvent>
#include <QSpinBox>
#include <QDir>
#include <QDirIterator>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QFont>
#include <QFontMetrics>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLinearGradient>
#include <QPalette>
#include <QPainter>
#include <QProxyStyle>
#include <QStyleOption>
#include <QWidget>
#include <QProcess>
#include <QRegularExpression>
#include <QTimer>

#include <cmath>
#include <functional>

namespace zones::editorTheme {

inline theme::Theme& current() {
    static theme::Theme value;
    return value;
}

inline QColor color(theme::Color value) {
    return QColor(int(value >> 24), int((value >> 16) & 0xff), int((value >> 8) & 0xff), int(value & 0xff));
}

inline QColor withAlpha(theme::Color value, double opacity) {
    auto result = color(value);
    result.setAlphaF(result.alphaF() * std::clamp(opacity, 0.0, 1.0));
    return result;
}

inline QString cssColor(const QColor& value) {
    return QString("rgba(%1,%2,%3,%4)").arg(value.red()).arg(value.green()).arg(value.blue()).arg(value.alpha());
}

inline QString cssColor(theme::Color value) { return cssColor(color(value)); }

inline std::pair<QPointF, QPointF> gradientEndpoints(double angle) {
    const double radians = angle * std::acos(-1.0) / 180.0;
    const QPointF direction(std::cos(radians) * 0.5, std::sin(radians) * 0.5);
    return {QPointF(0.5, 0.5) - direction, QPointF(0.5, 0.5) + direction};
}

inline QBrush gradientBrush(const theme::Gradient& definition, const QRectF& rect, double alpha = 1.0) {
    if (definition.colors.empty()) return color(current().accent);
    if (definition.colors.size() == 1) return withAlpha(definition.colors.front(), alpha);
    const auto [start, end] = gradientEndpoints(definition.angle);
    QLinearGradient gradient(rect.topLeft() + QPointF(start.x() * rect.width(), start.y() * rect.height()),
                             rect.topLeft() + QPointF(end.x() * rect.width(), end.y() * rect.height()));
    for (size_t i = 0; i < definition.colors.size(); ++i)
        gradient.setColorAt(double(i) / (definition.colors.size() - 1), withAlpha(definition.colors[i], alpha));
    return QBrush(gradient);
}

inline QString cssGradient(const theme::Gradient& gradient, double alpha) {
    if (gradient.colors.empty()) return cssColor(current().accent);
    if (gradient.colors.size() == 1) return cssColor(withAlpha(gradient.colors.front(), alpha));
    const auto [start, end] = gradientEndpoints(gradient.angle);
    QString output = QString("qlineargradient(x1:%1,y1:%2,x2:%3,y2:%4")
                         .arg(start.x()).arg(start.y()).arg(end.x()).arg(end.y());
    for (size_t i = 0; i < gradient.colors.size(); ++i)
        output += QString(",stop:%1 %2").arg(double(i) / (gradient.colors.size() - 1))
                      .arg(cssColor(withAlpha(gradient.colors[i], alpha)));
    return output + ")";
}

inline QColor composite(theme::Color foreground, double alpha, theme::Color background) {
    const auto top = withAlpha(foreground, alpha);
    const auto bottom = color(background);
    const auto blend = [&](int a, int b) { return qRound(a * top.alphaF() + b * (1 - top.alphaF())); };
    return QColor(blend(top.red(), bottom.red()), blend(top.green(), bottom.green()), blend(top.blue(), bottom.blue()));
}

// Qt's stylesheet border renderer draws separate arcs whose translucent ends
// overlap. Reserve its border space, then paint one closed path above the
// control. This child has no input, focus, or timer; the standard Qt control
// retains its own keyboard, mouse, accessibility, and standard-button roles.
inline theme::Control controlState(const QWidget& widget) {
    const auto& theme = current();
    if (widget.property("zonesPopupOutline").toBool())
        return {theme.foreground, 0, theme.activeBorder, 1, theme.borderWidth};
    if (!widget.isEnabled())
        return {theme.muted, 0, {{theme.muted}, 0}, .25, theme.normal.borderWidth};
    if (const auto button = qobject_cast<const QAbstractButton*>(&widget); button && button->isChecked())
        return theme.selected;
    if (widget.hasFocus()) return theme.focus;
    if (widget.underMouse()) return theme.hover;
    return theme.normal;
}

inline void drawOutline(QPainter& painter, const QRectF& rectangle, const theme::Control& state) {
    if (state.borderWidth <= 0 || rectangle.isEmpty()) return;
    const double inset = state.borderWidth / 2;
    const auto frame = rectangle.adjusted(inset, inset, -inset, -inset);
    if (frame.isEmpty()) return;
    const double radius = std::max(0., current().rounding - inset);
    QPainterPath path;
    path.addRoundedRect(frame, radius, radius);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setBrush(Qt::NoBrush);
    painter.setPen(QPen(gradientBrush(state.border, rectangle, state.borderAlpha), state.borderWidth));
    painter.drawPath(path);
}

class ControlOutline final : public QWidget {
public:
    explicit ControlOutline(QWidget* control) : QWidget(control) {
        setObjectName("zonesControlOutline");
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setAttribute(Qt::WA_NoSystemBackground);
        setFocusPolicy(Qt::NoFocus);
        setGeometry(control->rect());
        control->installEventFilter(this);
        show();
    }
protected:
    bool eventFilter(QObject* watched, QEvent* event) override {
        if (watched == parentWidget()) {
            if (event->type() == QEvent::Resize) setGeometry(parentWidget()->rect());
            if (event->type() == QEvent::Show || event->type() == QEvent::ChildAdded) raise();
        }
        return false;
    }
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        drawOutline(painter, QRectF(rect()), controlState(*parentWidget()));
    }
};

inline void enableContinuousOutline(QWidget* widget) {
    if (widget->property("zonesContinuousOutline").toBool()) return;
    widget->setProperty("zonesContinuousOutline", true);
    new ControlOutline(widget);
    // Standard dialog buttons may already have been polished before this call.
    widget->style()->unpolish(widget);
    widget->style()->polish(widget);
    widget->update();
}

class ControlStyler final : public QObject {
public:
    explicit ControlStyler(QApplication& app) : QObject(&app) { app.installEventFilter(this); }
protected:
    bool eventFilter(QObject* watched, QEvent* event) override {
        if (event->type() != QEvent::Show) return false;
        auto widget = qobject_cast<QWidget*>(watched);
        if (!widget) return false;
        const bool standaloneInput = qobject_cast<QLineEdit*>(widget) &&
            !qobject_cast<QAbstractSpinBox*>(widget->parentWidget()) &&
            !qobject_cast<QComboBox*>(widget->parentWidget());
        if (qobject_cast<QPushButton*>(widget) || standaloneInput)
            enableContinuousOutline(widget);
        return false;
    }
};

// Keep platform-dependent arrow controls on a local Qt base style. The widget
// owns this style; no application-wide style or ownership is changed.
class ArrowControlStyle final : public QProxyStyle {
public:
    ArrowControlStyle() : QProxyStyle("Fusion") {}
    int styleHint(StyleHint hint, const QStyleOption* option = nullptr, const QWidget* widget = nullptr,
                  QStyleHintReturn* data = nullptr) const override {
        // Use Qt's list popup instead of platform menu framing. Its contents
        // and border are drawn by the same theme as the closed control.
        if (hint == SH_ComboBox_Popup) return 0;
        return QProxyStyle::styleHint(hint, option, widget, data);
    }
};

inline void styleArrowControl(QWidget* widget) {
    auto style = new ArrowControlStyle;
    style->setParent(widget);
    widget->setStyle(style);
    enableContinuousOutline(widget);
}

inline void drawArrow(QPainter& painter, QRect rectangle, bool up, bool enabled) {
    const auto center = QRectF(rectangle).center();
    const double direction = up ? -1.0 : 1.0;
    const QPolygonF triangle{
        center + QPointF(-3.5, -direction * 2),
        center + QPointF(3.5, -direction * 2),
        center + QPointF(0, direction * 2),
    };
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(Qt::NoPen);
    painter.setBrush(color(enabled ? current().foreground : current().muted));
    painter.drawPolygon(triangle);
}

// Paint only arrow glyphs ourselves. Qt still owns subcontrol geometry, hit
// testing, repeat, keyboard, wheel, accessibility, and popup behavior.
class SpinBox final : public QSpinBox {
public:
    explicit SpinBox(QWidget* parent = nullptr) : QSpinBox(parent) { styleArrowControl(this); }
    QSize sizeHint() const override {
        auto size = QSpinBox::sizeHint();
        size.setHeight(std::max(size.height(), QFontMetrics(font()).height() + 18));
        return size;
    }
    QSize minimumSizeHint() const override {
        auto size = QSpinBox::minimumSizeHint();
        size.setHeight(sizeHint().height());
        return size;
    }
protected:
    void paintEvent(QPaintEvent* event) override {
        QSpinBox::paintEvent(event);
        QStyleOptionSpinBox option;
        initStyleOption(&option);
        QPainter painter(this);
        drawArrow(painter, style()->subControlRect(QStyle::CC_SpinBox, &option, QStyle::SC_SpinBoxUp, this),
                  true, isEnabled() && option.stepEnabled.testFlag(StepUpEnabled));
        drawArrow(painter, style()->subControlRect(QStyle::CC_SpinBox, &option, QStyle::SC_SpinBoxDown, this),
                  false, isEnabled() && option.stepEnabled.testFlag(StepDownEnabled));
    }
};

// A transparent popup needs an explicit rounded background. Keep it behind
// the standard item-view viewport, so Qt still renders and selects every row.
class PopupBackground final : public QWidget {
public:
    explicit PopupBackground(QWidget* popupView) : QWidget(popupView) {
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setAttribute(Qt::WA_NoSystemBackground);
        setFocusPolicy(Qt::NoFocus);
        setGeometry(popupView->rect());
        popupView->installEventFilter(this);
        lower();
        show();
    }
protected:
    bool eventFilter(QObject* watched, QEvent* event) override {
        if (watched == parentWidget() && event->type() == QEvent::Resize)
            setGeometry(parentWidget()->rect());
        return false;
    }
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setPen(Qt::NoPen);
        painter.setBrush(color(current().background));
        painter.drawRoundedRect(QRectF(rect()), current().rounding, current().rounding);
    }
};

class ComboBox final : public QComboBox {
public:
    explicit ComboBox(QWidget* parent = nullptr) : QComboBox(parent) {
        styleArrowControl(this);
        auto list = new QListView(this);
        list->setFrameShape(QFrame::NoFrame);
        list->setAutoFillBackground(false);
        list->setAttribute(Qt::WA_TranslucentBackground);
        list->setProperty("zonesPopupOutline", true);
        list->viewport()->setAutoFillBackground(false);
        setView(list);
        new PopupBackground(list);
        enableContinuousOutline(list);
        // QComboBox supplies the popup container. Public widget attributes keep
        // its corners transparent without depending on Qt's private classes.
        auto popup = list->window();
        popup->setObjectName("zonesPopupContainer");
        popup->setAttribute(Qt::WA_TranslucentBackground);
        popup->setAutoFillBackground(false);
    }
    QSize sizeHint() const override {
        auto result = QComboBox::sizeHint();
        QStyleOptionComboBox option;
        initStyleOption(&option);
        const int contentHeight = std::max(QFontMetrics(font()).height(), iconSize().height());
        const auto fitted = style()->sizeFromContents(QStyle::CT_ComboBox, &option,
                                                       QSize(0, contentHeight), this);
        result.setHeight(std::max(result.height(), fitted.height()));
        return result;
    }
    QSize minimumSizeHint() const override {
        auto result = QComboBox::minimumSizeHint();
        result.setHeight(std::max(result.height(), sizeHint().height()));
        return result;
    }
protected:
    bool event(QEvent* event) override {
        const bool handled = QComboBox::event(event);
        if (!updatingMinimum && (event->type() == QEvent::Polish || event->type() == QEvent::Show ||
                                event->type() == QEvent::StyleChange || event->type() == QEvent::FontChange)) {
            // QSS min-height becomes an explicit QWidget minimum and overrides
            // minimumSizeHint during constrained layout. Restore the minimum
            // derived from real content and style metrics after each repolish.
            updatingMinimum = true;
            setMinimumHeight(sizeHint().height());
            updatingMinimum = false;
        }
        return handled;
    }
    void paintEvent(QPaintEvent* event) override {
        QComboBox::paintEvent(event);
        QStyleOptionComboBox option;
        initStyleOption(&option);
        QPainter painter(this);
        drawArrow(painter, style()->subControlRect(QStyle::CC_ComboBox, &option, QStyle::SC_ComboBoxArrow, this),
                  false, isEnabled());
    }
private:
    bool updatingMinimum = false;
};

inline QString controlCss(const theme::Control& state, const theme::Theme& theme) {
    return QString("color:%1; background-color:%2; border:%3px solid transparent;")
        .arg(cssColor(state.color), cssColor(composite(state.color, state.fillAlpha, theme.background)))
        .arg(state.borderWidth);
}

inline void apply(QApplication& app, const theme::Theme& theme) {
    current() = theme;
    if (!app.property("zonesControlStylerInstalled").toBool()) {
        app.setProperty("zonesControlStylerInstalled", true);
        new ControlStyler(app);
    }
    QPalette palette;
    for (const auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
        const bool disabled = group == QPalette::Disabled;
        const auto text = color(disabled ? theme.muted : theme.foreground);
        palette.setColor(group, QPalette::Window, color(theme.background));
        palette.setColor(group, QPalette::WindowText, text);
        palette.setColor(group, QPalette::Base, color(theme.surface));
        palette.setColor(group, QPalette::AlternateBase, color(theme.raised));
        palette.setColor(group, QPalette::Text, text);
        palette.setColor(group, QPalette::Button, color(theme.raised));
        palette.setColor(group, QPalette::ButtonText, text);
        palette.setColor(group, QPalette::Highlight, color(theme.accent));
        palette.setColor(group, QPalette::HighlightedText, color(theme.background));
        palette.setColor(group, QPalette::PlaceholderText, color(theme.muted));
        palette.setColor(group, QPalette::ToolTipBase, color(theme.background));
        palette.setColor(group, QPalette::ToolTipText, color(theme.foreground));
        palette.setColor(group, QPalette::Link, color(theme.accent));
        palette.setColor(group, QPalette::LinkVisited, color(theme.accent));
        palette.setColor(group, QPalette::Light, color(theme.raised));
        palette.setColor(group, QPalette::Midlight, color(theme.raised));
        palette.setColor(group, QPalette::Mid, color(theme.muted));
        palette.setColor(group, QPalette::Dark, color(theme.surface));
        palette.setColor(group, QPalette::Shadow, color(theme.surface));
        palette.setColor(group, QPalette::Accent, color(theme.accent));
    }
    app.setPalette(palette);
    // Omarchy shell binds its font family to the fontconfig monospace alias.
    QFont font("monospace");
    font.setPixelSize(qRound(theme.fontSize));
    app.setFont(font);

    // Every value substituted below is parsed and bounded by the shared theme
    // reader. Raw theme text is never copied into a Qt style sheet.
    const QString controls = "QPushButton, QComboBox, QSpinBox, QLineEdit";
    QString css = QString("QWidget { color:%1; } QMainWindow, QDialog, QMessageBox { background:%2; }")
                      .arg(cssColor(theme.foreground), cssColor(theme.background));
    css += controls + " { " + controlCss(theme.normal, theme)
        + QString("border-radius:%1px; padding:6px 10px; min-height:18px; }").arg(theme.rounding);
    css += "QComboBox, QSpinBox { padding-right:26px; }";
    css += "QPushButton:hover, QComboBox:hover, QSpinBox:hover, QLineEdit:hover { " + controlCss(theme.hover, theme) + " }";
    css += "QPushButton:focus, QComboBox:focus, QSpinBox:focus, QLineEdit:focus { " + controlCss(theme.focus, theme) + " }";
    css += "QPushButton:checked { " + controlCss(theme.selected, theme) + " }";
    css += QString("QPushButton:pressed { background:%1; }")
               .arg(cssColor(composite(theme.pressedColor, theme.pressedFillAlpha, theme.background)));
    css += QString("QPushButton:disabled, QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled { color:%1; border-color:%2; background:%3; }")
               .arg(cssColor(theme.muted), QString("transparent"), cssColor(theme.background));
    css += QString("QLineEdit, QSpinBox { selection-background-color:%1; selection-color:%2; }")
               .arg(cssColor(composite(theme.selectionColor, theme.selectionFillAlpha, theme.background)), cssColor(theme.foreground));
    css += QString("QComboBox QAbstractItemView { color:%1; background:%2; border:%3px solid transparent; outline:0; selection-background-color:%4; selection-color:%5; padding:4px; }")
               .arg(cssColor(theme.foreground), cssColor(theme.background)).arg(theme.borderWidth)
               .arg(cssColor(composite(theme.selected.color, theme.selected.fillAlpha, theme.background)), cssColor(theme.accent));
    css += QString("QComboBox QAbstractItemView::item { min-height:30px; padding:3px 6px; }");
    css += "QComboBox::drop-down { subcontrol-origin:border; subcontrol-position:center right; right:4px; border:0; width:18px; }";
    css += "QSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right; top:3px; right:3px; width:18px; height:12px; border:0; background:transparent; }";
    css += "QSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right; bottom:3px; right:3px; width:18px; height:12px; border:0; background:transparent; }";
    css += QString("QToolTip { color:%1; background:%2; border:%3px solid %4; border-radius:%5px; padding:6px; }")
               .arg(cssColor(theme.foreground), cssColor(theme.background)).arg(theme.borderWidth)
               .arg(cssGradient(theme.activeBorder, 1)).arg(theme.rounding);
    // A spinbox owns an internal QLineEdit. It must not receive a second
    // field border, padding, or minimum height from the standalone input rule.
    css += "QSpinBox QLineEdit, QSpinBox QLineEdit:hover, QSpinBox QLineEdit:focus, QSpinBox QLineEdit:disabled { border:0; border-radius:0; background:transparent; padding:0; margin:0; min-height:0; }";
    css += QString("QLabel[role=muted] { color:%1; } QLabel[role=error] { color:%2; } QFrame[frameShape=4] { color:%3; }")
               .arg(cssColor(theme.muted), cssColor(theme.error), cssColor(withAlpha(theme.muted, 0.4)));
    css += "QWidget#zonesPopupContainer { background:transparent; border:0; }";
    css += QString("QComboBox QAbstractItemView[zonesContinuousOutline=true] { border-radius:%1px; }")
               .arg(theme.rounding);
    css += QString("QScrollBar:vertical { background:transparent; width:8px; margin:0; } "
                   "QScrollBar:horizontal { background:transparent; height:8px; margin:0; } "
                   "QScrollBar::handle { background:%1; border-radius:4px; min-height:24px; min-width:24px; } "
                   "QScrollBar::handle:hover { background:%2; } "
                   "QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; border:0; background:transparent; } "
                   "QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }")
               .arg(cssColor(composite(theme.muted, .4, theme.background)),
                    cssColor(composite(theme.foreground, .4, theme.background)));
    app.setStyleSheet(css);
}

// Theme changes wake this object through filesystem notifications. Hyprctl is
// a short-lived child only when refreshing; its deadline is a one-shot timer.
class Controller final : public QObject {
public:
    explicit Controller(QApplication& app) : QObject(&app), application(app) {
        debounce.setSingleShot(true);
        timeout.setSingleShot(true);
        connect(&debounce, &QTimer::timeout, this, [this] { refresh(); });
        connect(&timeout, &QTimer::timeout, this, [this] { query.kill(); });
        connect(&watcher, &QFileSystemWatcher::fileChanged, this, [this] { schedule(); });
        connect(&watcher, &QFileSystemWatcher::directoryChanged, this, [this] { schedule(); });
        connect(&query, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
            timeout.stop();
            if (code == 0 && status == QProcess::NormalExit) readCompositorStyle(query.readAllStandardOutput());
            publish();
            if (refreshPending) { refreshPending = false; schedule(); }
        });
        connect(&query, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
            if (error == QProcess::FailedToStart) { timeout.stop(); publish(); }
        });
        refresh();
    }

    ~Controller() override {
        if (query.state() != QProcess::NotRunning) {
            query.kill();
            query.waitForFinished(1000);
        }
    }

    std::function<void()> onChanged;

private:
    QApplication& application;
    QFileSystemWatcher watcher;
    QProcess query;
    QTimer debounce, timeout;
    theme::Theme loaded;
    bool refreshPending = false;

    void schedule() { debounce.start(200); }

    void reattachWatches() {
        QStringList wanted;
        const auto themeDirectory = QString::fromStdString(theme::directory().string());
        wanted << QFileInfo(themeDirectory).absolutePath() << themeDirectory
               << themeDirectory + "/colors.toml" << themeDirectory + "/shell.toml";
        QString config = qEnvironmentVariable("XDG_CONFIG_HOME");
        if (config.isEmpty()) config = QDir::homePath() + "/.config";
        const QString hyprland = config + "/hypr";
        const QString stateDirectory = QFileInfo(QFileInfo(themeDirectory).absolutePath()).absolutePath();
        wanted << hyprland << config + "/fontconfig" << config + "/fontconfig/fonts.conf"
               << stateDirectory + "/toggles/hypr" << stateDirectory + "/toggles/hypr/window-no-gaps.lua";
        // Local configuration can be split into several files/directories.
        // The bound prevents malformed trees from allocating unlimited watches.
        QDirIterator entries(hyprland, QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot, QDirIterator::Subdirectories);
        while (entries.hasNext() && wanted.size() < 128) wanted << entries.next();
        // A theme directory may be a replaced symlink. Re-arm the same paths
        // against their current targets, rather than keeping an old inode.
        const auto oldFiles = watcher.files();
        const auto oldDirectories = watcher.directories();
        if (!oldFiles.isEmpty()) watcher.removePaths(oldFiles);
        if (!oldDirectories.isEmpty()) watcher.removePaths(oldDirectories);
        wanted.removeDuplicates();
        for (const auto& path : wanted) {
            if (QFileInfo::exists(path) && !watcher.files().contains(path) && !watcher.directories().contains(path))
                watcher.addPath(path);
        }
    }

    void refresh() {
        if (query.state() != QProcess::NotRunning) { refreshPending = true; return; }
        reattachWatches();
        loaded = theme::load(theme::directory());
        // Paint file tokens immediately. Live compositor values replace only
        // border appearance once the bounded asynchronous query completes.
        publish();
        query.start("hyprctl", {"-j", "--batch", "getoption general:col.active_border; getoption general:col.inactive_border; getoption general:border_size; getoption decoration:rounding"});
        timeout.start(1500);
    }

    void readCompositorStyle(const QByteArray& bytes) {
        if (bytes.size() > 16384) return;
        // Hyprctl --batch returns separate JSON objects separated by whitespace.
        // These four known options contain only scalar values, not nested JSON.
        const QRegularExpression objectExpression("\\{[^{}]*\\}");
        auto matches = objectExpression.globalMatch(QString::fromUtf8(bytes));
        while (matches.hasNext()) {
            const auto object = QJsonDocument::fromJson(matches.next().captured().toUtf8()).object();
            const auto option = object["option"].toString();
            if (option == "general:col.active_border" || option == "general:col.inactive_border") {
                const auto gradient = theme::parseGradient(object["gradient"].toString().toStdString(), true);
                if (gradient) (option == "general:col.active_border" ? loaded.activeBorder : loaded.inactiveBorder) = *gradient;
            } else if (option == "general:border_size" && object["int"].isDouble()) {
                loaded.borderWidth = std::clamp(object["int"].toDouble(), 0.0, 16.0);
            } else if (option == "decoration:rounding" && object["int"].isDouble()) {
                loaded.rounding = std::clamp(object["int"].toDouble(), 0.0, 64.0);
            }
        }
    }

    void publish() {
        apply(application, loaded);
        if (onChanged) onChanged();
    }
};

} // namespace zones::editorTheme
