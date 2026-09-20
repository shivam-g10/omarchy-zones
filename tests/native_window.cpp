// A real Wayland client for native drag integration tests. This is not the editor.
#include <QApplication>
#include <QLabel>
#include <QMouseEvent>
#include <QPushButton>
#include <QVBoxLayout>
#include <QWindow>
#include <QWidget>
#include <iostream>

class DragHeader : public QLabel {
public:
    explicit DragHeader(QWidget* parent) : QLabel("Drag this title bar", parent) {
        setMinimumHeight(56);
        setAlignment(Qt::AlignCenter);
        setStyleSheet("background:#385a7a;color:white;font-size:19px;border-radius:8px;");
    }
protected:
    void mousePressEvent(QMouseEvent* event) override {
        if (event->button() == Qt::LeftButton && window()->windowHandle()) {
            const bool accepted = window()->windowHandle()->startSystemMove();
            std::cout << "startSystemMove " << (accepted ? "accepted" : "rejected") << std::endl;
            event->accept();
        } else QLabel::mousePressEvent(event);
    }
};

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    app.setApplicationName("omarchy-zones-native-test");
    app.setDesktopFileName("omarchy-zones-native-test");
    QWidget window;
    window.setWindowTitle(argc > 1 ? argv[1] : "Zones native test window");
    window.setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
    window.setMinimumSize(100, 100);
    window.resize(600, 400);
    auto* layout = new QVBoxLayout(&window);
    layout->setContentsMargins(10, 10, 10, 10);
    layout->addWidget(new DragHeader(&window));
    auto* body = new QLabel("Native Wayland test window\n\n"
        "Title bar: compositor-managed drag\n"
        "Super + left drag: existing desktop binding\n\n"
        "Geometry is measured through hyprctl clients.", &window);
    body->setAlignment(Qt::AlignCenter);
    body->setStyleSheet("font-size:18px;color:#dde5ed;");
    layout->addWidget(body, 1);
    auto* close = new QPushButton("Close test window", &window);
    QObject::connect(close, &QPushButton::clicked, &window, &QWidget::close);
    layout->addWidget(close);
    window.setStyleSheet("QWidget { background:#1b222c; } QPushButton { color:#dde5ed; padding:8px; }");
    window.show();
    std::cout << "platform " << QGuiApplication::platformName().toStdString() << std::endl;
    return app.exec();
}
