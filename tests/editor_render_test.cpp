// Render real Qt widgets offscreen. Pixel bounds catch the translucent corner
// seam while interaction checks keep decoration separate from control behavior.
#include "../src/editor_theme.hpp"

#include <QDialogButtonBox>
#include <QKeyEvent>
#include <QHBoxLayout>
#include <QMouseEvent>
#include <QTemporaryDir>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void key(QWidget& target, int value) {
    QKeyEvent press(QEvent::KeyPress, value, Qt::NoModifier);
    QKeyEvent release(QEvent::KeyRelease, value, Qt::NoModifier);
    QApplication::sendEvent(&target, &press);
    QApplication::sendEvent(&target, &release);
}
void click(QWidget& target, QPointF point) {
    QMouseEvent press(QEvent::MouseButtonPress, point, target.mapToGlobal(point.toPoint()),
                      Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
    QMouseEvent release(QEvent::MouseButtonRelease, point, target.mapToGlobal(point.toPoint()),
                        Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
    QApplication::sendEvent(&target, &press);
    QApplication::sendEvent(&target, &release);
}
void noCornerSeam(QWidget& widget, const QString& output) {
    const auto image = widget.grab().toImage();
    const double scale = image.devicePixelRatio();
    const int corner = qRound(zones::editorTheme::current().rounding * scale);
    int straight = 0, peak = 0;
    for (int y = 0; y < qCeil(2 * scale); ++y)
        straight = std::max(straight, image.pixelColor(image.width() / 2, y).red());
    for (int y = 0; y < corner; ++y)
        for (int x = 0; x < corner; ++x)
            peak = std::max(peak, image.pixelColor(x, y).red());
    std::cout << output.toStdString() << " DPR=" << scale << " straight=" << straight << " corner=" << peak << '\n';
    require(straight > zones::editorTheme::color(zones::editorTheme::current().background).red() + 10, "The control outline disappeared");
    require(peak <= straight + 2, "A translucent corner is brighter than the straight border");
    if (!qEnvironmentVariableIsEmpty("ZONES_RENDER_OUTPUT"))
        image.save(qEnvironmentVariable("ZONES_RENDER_OUTPUT") + "/" + output + ".png");
}
} // namespace

int main(int argc, char** argv) {
    try {
        QApplication app(argc, argv);
        auto theme = zones::theme::Theme{};
        theme.rounding = 12;
        theme.borderWidth = 3;
        theme.activeBorder = {{0x72f1ffff, 0xffc857ff}, 45};
        theme.hover = theme.focus = theme.selected = theme.normal;
        zones::editorTheme::apply(app, theme);

        QWidget host;
        host.setAutoFillBackground(true);
        host.resize(520, 310);
        QPushButton button("", &host);
        button.setGeometry(20, 20, 200, 40);
        zones::editorTheme::ComboBox combo(&host);
        combo.setGeometry(250, 20, 240, 54);
        QPixmap icon(48, 28); icon.fill(Qt::cyan);
        combo.setIconSize({48, 28});
        combo.addItem(QIcon(icon), "First profile");
        combo.addItem(QIcon(icon), "Second profile");
        zones::editorTheme::SpinBox spin(&host);
        spin.setGeometry(20, 90, 200, 40);
        spin.setValue(50);
        QLineEdit input(&host);
        input.setGeometry(250, 90, 240, 40);
        QDialogButtonBox buttons(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &host);
        buttons.setGeometry(20, 160, 470, 60);
        for (auto control : {static_cast<QWidget*>(&button), static_cast<QWidget*>(&combo), static_cast<QWidget*>(&spin), static_cast<QWidget*>(&input)})
            control->setFocusPolicy(Qt::NoFocus);
        host.show(); app.processEvents();
        for (auto control : {static_cast<QWidget*>(&button), static_cast<QWidget*>(&combo),
                             static_cast<QWidget*>(&spin), static_cast<QWidget*>(&input)}) {
            require(control->property("zonesContinuousOutline").toBool(), "A control was not decorated");
            noCornerSeam(*control, control == &button ? "button" : control == &combo ? "combo" : control == &spin ? "spin" : "input");
        }
        auto standardOk = buttons.button(QDialogButtonBox::Ok);
        require(standardOk && standardOk->property("zonesContinuousOutline").toBool(), "A standard dialog button was not decorated");
        require(buttons.buttonRole(standardOk) == QDialogButtonBox::AcceptRole, "Decoration changed a standard button role");
        zones::editorTheme::apply(app, theme);
        app.processEvents();
        require(standardOk->findChildren<QWidget*>("zonesControlOutline").size() == 1, "A theme update duplicated an outline");
        bool accepted = false;
        QObject::connect(&buttons, &QDialogButtonBox::accepted, &app, [&] { accepted = true; });
        standardOk->click();
        require(accepted, "A standard dialog button lost its accepted signal");

        int presses = 0;
        QObject::connect(&button, &QPushButton::clicked, &app, [&] { ++presses; });
        click(button, button.rect().center());
        require(presses == 1, "An outline consumed a button click");
        click(spin, QPointF(spin.width() - 12, 9));
        require(spin.value() == 51, "The increment arrow lost its hit target");
        key(spin, Qt::Key_Down);
        require(spin.value() == 50, "The spinbox lost keyboard stepping");
        key(combo, Qt::Key_Down);
        require(combo.currentIndex() == 1, "The combo lost keyboard selection");
        auto internalInput = spin.findChild<QLineEdit*>();
        require(internalInput && !internalInput->property("zonesContinuousOutline").toBool(), "The spinbox received a duplicate inner frame");

        // Let the layout negotiate height in a deliberately short row. QSS
        // used to override the larger size hint with its 18-pixel content min.
        QWidget constrainedRow;
        constrainedRow.resize(420, 30);
        auto row = new QHBoxLayout(&constrainedRow);
        auto fittedCombo = new zones::editorTheme::ComboBox;
        fittedCombo->setIconSize({48, 28});
        fittedCombo->addItem(QIcon(icon), "Layout thumbnail");
        row->addWidget(fittedCombo);
        row->addWidget(new QPushButton("Action"));
        constrainedRow.show();
        app.processEvents();
        QStyleOptionComboBox fittedOption;
        fittedOption.initFrom(fittedCombo);
        fittedOption.rect = fittedCombo->rect();
        fittedOption.iconSize = fittedCombo->iconSize();
        const auto fittedContents = fittedCombo->style()->subControlRect(QStyle::CC_ComboBox, &fittedOption,
                                                                        QStyle::SC_ComboBoxEditField, fittedCombo);
        require(fittedContents.height() >= fittedCombo->iconSize().height(), "A constrained layout clips the profile thumbnail");
        zones::editorTheme::apply(app, theme);
        app.processEvents();
        require(fittedCombo->height() >= fittedCombo->minimumSizeHint().height(), "Theme repolishing shrinks the thumbnail control");
        QStyleOptionComboBox option;
        option.initFrom(&combo);
        option.rect = combo.rect();
        option.iconSize = combo.iconSize();
        const auto contents = combo.style()->subControlRect(QStyle::CC_ComboBox, &option,
                                                            QStyle::SC_ComboBoxEditField, &combo);
        require(contents.height() >= combo.iconSize().height(), "The combo clips its configured thumbnail");
        combo.showPopup(); app.processEvents();
        require(combo.view()->window()->testAttribute(Qt::WA_TranslucentBackground), "The popup has opaque square corners");
        const auto popup = combo.view()->window()->grab().toImage();
        require(popup.pixelColor(0, 0).alpha() == 0, "The popup still paints a square background corner");
        const auto popupFill = popup.pixelColor(popup.width() - qRound(12 * popup.devicePixelRatio()), popup.height() / 4);
        require(popupFill == zones::editorTheme::color(theme.background), "The popup lost its opaque theme background");
        if (!qEnvironmentVariableIsEmpty("ZONES_RENDER_OUTPUT")) {
            host.grab().save(qEnvironmentVariable("ZONES_RENDER_OUTPUT") + "/controls.png");
            combo.view()->window()->grab().save(qEnvironmentVariable("ZONES_RENDER_OUTPUT") + "/popup.png");
        }
        combo.hidePopup();
        button.setEnabled(false); app.processEvents();
        noCornerSeam(button, "disabled");
        std::cout << "PASS continuous borders, standard dialog roles, thumbnails and input behavior\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
