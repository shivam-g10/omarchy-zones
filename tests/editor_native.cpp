// Run the production editor with a test-only F12 inspection shortcut. Pointer
// and key events still arrive from the isolated compositor's real Wayland seat.
#define main zones_editor_application_main
#include "../src/editor.cpp"
#undef main
#include <QFontInfo>
#include <iostream>

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    app.setApplicationName("Omarchy Zones native check");
    app.setDesktopFileName("omarchy-zones-editor");
    zones::editorInstance::Service instance;
    if (instance.start(configPath()) != zones::editorInstance::Service::Result::Primary) {
        std::cerr << instance.errorString().toStdString() << '\n';
        return 1;
    }
    zones::editorTheme::Controller themeController(app);
    QString error;
    auto monitors = readMonitors(error);
    zones::Profiles profiles;
    bool fresh = false, legacy = false;
    if (monitors.empty() || !readSavedProfiles(profiles, monitors, fresh, legacy, error)) {
        std::cerr << error.toStdString() << '\n';
        return 1;
    }
    Editor editor(std::move(monitors), std::move(profiles), fresh, legacy);
    zones::editorInstance::Activation activation(editor);
    instance.onActivate([&activation] { activation.request(); });
    editor.setWindowTitle("Omarchy Zones native check");
    const QPointer<Editor> guardedEditor(&editor);
    themeController.onChanged = [guardedEditor] { if (guardedEditor) guardedEditor->refreshTheme(); };
    auto report = [&] {
        const auto center = [&](QWidget* widget) {
            const auto point = widget->mapTo(&editor, widget->rect().center());
            return QJsonObject{{"x", point.x()}, {"y", point.y()}};
        };
        const auto canvas = static_cast<Canvas*>(editor.findChild<QWidget*>("zoneCanvas"));
        const auto width = editor.findChild<QSpinBox*>("widthValue");
        const auto heightField = editor.findChild<QSpinBox*>("heightValue");
        const auto profile = editor.findChild<QComboBox*>("profileChoice");
        QStyleOptionComboBox profileOption;
        profileOption.initFrom(profile);
        profileOption.editable = profile->isEditable();
        profileOption.frame = profile->hasFrame();
        profileOption.iconSize = profile->iconSize();
        const auto profileContent = profile->style()->subControlRect(
            QStyle::CC_ComboBox, &profileOption, QStyle::SC_ComboBoxEditField, profile);
        QLabel* geometryHelp = nullptr;
        for (auto label : editor.findChildren<QLabel*>())
            if (label->text().startsWith("X / Y move a zone.")) geometryHelp = label;
        const bool fieldLayoutFits = geometryHelp &&
            heightField->mapTo(&editor, heightField->rect().bottomLeft()).y() <
                geometryHelp->mapTo(&editor, QPoint{}).y();
        const auto& monitor = canvas->monitor;
        const double scale = std::min((canvas->width() - 48.0) / monitor.width,
                                      (canvas->height() - 78.0) / monitor.height);
        const QPoint origin = canvas->mapTo(&editor, QPoint{});
        const QPointF screenOrigin((canvas->width() - monitor.width * scale) / 2,
                                    (canvas->height() - 30 - monitor.height * scale) / 2);
        const auto rectangle = canvas->rectangles->at(0);
        const auto boundary = QPointF(origin) + screenOrigin
            + QPointF(rectangle.right() * scale, (rectangle.y + rectangle.h / 2.0) * scale);
        const auto& theme = zones::editorTheme::current();
        QJsonArray borders, rectangles;
        for (auto value : theme.activeBorder.colors) borders.append(QString::number(value, 16));
        for (const auto& r : *canvas->rectangles) rectangles.append(QJsonArray{r.x, r.y, r.w, r.h});
        const QJsonObject state{
            {"width", editor.width()}, {"height", editor.height()},
            {"input", center(width)}, {"save", center(editor.findChild<QPushButton*>("saveZones"))},
            {"profile", center(profile)},
            {"newProfile", center(editor.findChild<QPushButton*>("addProfile"))},
            {"profileIconFits", profileContent.height() >= profile->iconSize().height()},
            {"profileIconHeight", profile->iconSize().height()},
            {"profileContentHeight", profileContent.height()},
            {"boundary", QJsonObject{{"x", boundary.x()}, {"y", boundary.y()}}},
            {"boundaryValue", width->value()}, {"rectangles", rectangles},
            {"fieldsDoNotOverlapHelp", fieldLayoutFits},
            {"fontFamily", QFontInfo(app.font()).family()},
            {"theme", QJsonObject{{"accent", QString::number(theme.accent, 16)},
                {"borderColors", borders}, {"borderAngle", theme.activeBorder.angle},
                {"borderWidth", theme.borderWidth}, {"rounding", theme.rounding},
                {"controlFill", theme.normal.fillAlpha}, {"fontSize", theme.fontSize}}}};
        std::cout << "AUTOMATION " << QJsonDocument(state).toJson(QJsonDocument::Compact).toStdString() << std::endl;
    };
    QShortcut shortcut(QKeySequence("F12"), &editor);
    QObject::connect(&shortcut, &QShortcut::activated, &app, report);
    editor.show();
    return app.exec();
}
