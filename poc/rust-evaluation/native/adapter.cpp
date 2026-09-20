#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include "bridge.h"

#include <linux/input-event-codes.h>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace {
HANDLE handle = nullptr;
std::vector<CHyprSignalListener> listeners;
SP<SHyprCtlCommand> command;
WP<Layout::ITarget> dragged;
RustLayout layout{};
std::string monitorName;
bool visible = false;
bool cancelled = false;
bool callbackFailure = false;
int hovered = -1;
uint64_t pendingSnap = 0, pendingRefresh = 0, snaps = 0, rustCalls = 0;

PHLMONITOR namedMonitor(const std::string& name) {
    for (const auto& monitor : State::monitorState()->monitors())
        if (monitor->m_name == name) return monitor;
    return nullptr;
}

PHLMONITOR pointerMonitor(Vector2D point) {
    for (const auto& monitor : State::monitorState()->monitors())
        if (point.x >= monitor->m_position.x && point.y >= monitor->m_position.y &&
            point.x < monitor->m_position.x + monitor->m_size.x &&
            point.y < monitor->m_position.y + monitor->m_size.y) return monitor;
    return nullptr;
}

RustRect usableArea(const PHLMONITOR& monitor) {
    const int x = std::ceil(monitor->m_reservedArea.left());
    const int y = std::ceil(monitor->m_reservedArea.top());
    return {x, y, static_cast<int>(std::floor(monitor->m_size.x - monitor->m_reservedArea.right())) - x,
                  static_cast<int>(std::floor(monitor->m_size.y - monitor->m_reservedArea.bottom())) - y};
}

CBox box(RustRect rectangle, const PHLMONITOR& monitor) {
    return {monitor->m_position.x + rectangle.x, monitor->m_position.y + rectangle.y,
            static_cast<double>(rectangle.w), static_cast<double>(rectangle.h)};
}

void damage() {
    if (const auto monitor = namedMonitor(monitorName)) g_pHyprRenderer->damageMonitor(monitor);
}

void hide() {
    if (visible) damage();
    visible = false;
    hovered = -1;
}

bool shiftDown() { return (g_pInputManager->getModsFromAllKBs() & 1U) != 0; }

// Compositor callbacks must not leak exceptions into Hyprland's event dispatch.
template<class Function> void guarded(Function&& function) noexcept {
    try { function(); }
    catch (...) { callbackFailure = true; visible = false; hovered = -1; dragged.reset(); }
}

void update(Vector2D cursor) {
    const auto& controller = g_layoutManager->dragController();
    const auto target = controller->target();
    if (callbackFailure || g_pSessionLockManager->isSessionLocked()) { hide(); return; }
    if (!target || controller->mode() != MBIND_MOVE || target->type() != Layout::TARGET_TYPE_WINDOW ||
        !target->window() || !target->window()->m_isMapped || target->window()->m_group) {
        hide(); dragged.reset(); cancelled = false; return;
    }
    static auto threshold = CConfigValue<Config::INTEGER>("binds:drag_threshold");
    if (!shiftDown() || (*threshold > 0 && !controller->dragThresholdReached())) { hide(); return; }
    if (dragged.lock() != target) { hide(); dragged = target; cancelled = false; }
    if (cancelled) { hide(); return; }
    const auto monitor = pointerMonitor(cursor);
    if (!monitor) { hide(); return; }
    if (!visible || monitorName != monitor->m_name) {
        hide(); monitorName = monitor->m_name;
        ++rustCalls;
        layout = zones_rust_split(usableArea(monitor));
    }
    if (layout.valid != 1) { hide(); return; }
    ++rustCalls;
    const int next = zones_rust_hit(layout, cursor.x - monitor->m_position.x, cursor.y - monitor->m_position.y);
    if (!visible || next != hovered) { visible = true; hovered = next; damage(); }
}

void queueRefresh() {
    if (pendingRefresh) return;
    pendingRefresh = g_pEventLoopManager->doLater([] {
        pendingRefresh = 0;
        guarded([] { update(g_pInputManager->getMouseCoordsInternal()); });
    });
}

void release(const IPointer::SButtonEvent& event) {
    if (event.button != BTN_LEFT || event.state != WL_POINTER_BUTTON_STATE_RELEASED) return;
    const auto target = dragged.lock();
    const auto monitor = namedMonitor(monitorName);
    const auto& controller = g_layoutManager->dragController();
    const bool qualified = visible && target && monitor && !cancelled && shiftDown() &&
        !g_pSessionLockManager->isSessionLocked() && controller->mode() == MBIND_MOVE && controller->target() == target;
    RustDrop result{};
    if (qualified) {
        const auto cursor = g_pInputManager->getMouseCoordsInternal();
        ++rustCalls;
        result = zones_rust_drop(layout, cursor.x - monitor->m_position.x, cursor.y - monitor->m_position.y, 1);
    }
    hide(); dragged.reset(); cancelled = false;
    if (!result.should_snap) return;
    if (pendingSnap) g_pEventLoopManager->removeDoLater(pendingSnap);
    const WP<Layout::ITarget> weakTarget = target;
    const std::string name = monitorName;
    // Only this one-shot callback holds a weak reference; no assignment survives it.
    pendingSnap = g_pEventLoopManager->doLater([weakTarget, result, name] {
        pendingSnap = 0;
        guarded([&] {
            const auto target = weakTarget.lock();
            const auto monitor = namedMonitor(name);
            const auto r = result.rectangle;
            if (g_pSessionLockManager->isSessionLocked() || !target || !monitor || !target->window() ||
                !target->window()->m_isMapped || target->window()->m_group || g_layoutManager->dragController()->target()) return;
            const auto current = usableArea(monitor);
            if (r.x < current.x || r.y < current.y || r.x + r.w > current.x + current.w || r.y + r.h > current.y + current.h) return;
            const auto minimum = target->minSize();
            const auto maximum = target->maxSize();
            if ((minimum && (r.w < minimum->x || r.h < minimum->y)) ||
                (maximum && (r.w > maximum->x || r.h > maximum->y))) return;
            const auto workspace = monitor->m_activeSpecialWorkspace ? monitor->m_activeSpecialWorkspace : monitor->m_activeWorkspace;
            if (!workspace || !workspace->m_space) return;
            if (!target->floating()) g_layoutManager->changeFloatingMode(target);
            if (target->workspace() != workspace) target->assignToSpace(workspace->m_space);
            target->damageEntire();
            g_layoutManager->setTargetGeom(box(r, monitor), target);
            target->damageEntire();
            ++snaps;
        });
    });
}

void rectangle(CBox box, CHyprColor color) {
    CRectPassElement::SRectData data;
    data.box = box; data.color = color;
    g_pHyprRenderer->addPassElement(makeUnique<CRectPassElement>(data));
}

void render(eRenderStage stage) {
    if (stage != RENDER_LAST_MOMENT || !visible || g_pSessionLockManager->isSessionLocked()) return;
    const auto monitor = g_pHyprRenderer->renderData().pMonitor.lock();
    if (!monitor || monitor->m_name != monitorName) return;
    for (int i = 0; i < 2; ++i) {
        const auto r = layout.zones[i];
        const double scale = monitor->m_scale;
        CBox b(r.x * scale, r.y * scale, r.w * scale, r.h * scale);
        const bool selected = i == hovered;
        const double width = (selected ? 4.0 : 2.0) * scale;
        const CHyprColor edge(0.3F, 0.8F, 0.95F, selected ? 1.F : .55F);
        rectangle(b, edge.modifyA(selected ? .28F : .06F));
        rectangle({b.x, b.y, b.w, width}, edge);
        rectangle({b.x, b.y + b.h - width, b.w, width}, edge);
        rectangle({b.x, b.y, width, b.h}, edge);
        rectangle({b.x + b.w - width, b.y, width, b.h}, edge);
    }
}

void reset() {
    hide(); dragged.reset(); cancelled = true;
    if (pendingSnap) g_pEventLoopManager->removeDoLater(pendingSnap);
    if (pendingRefresh) g_pEventLoopManager->removeDoLater(pendingRefresh);
    pendingSnap = pendingRefresh = 0;
}

std::string status() {
    std::ostringstream out;
    out << "zones-rust-poc: 0.1.0\n"
        << "overlay: " << (visible ? "visible" : "hidden") << '\n'
        << "hovered-zone: " << hovered << '\n'
        << "snaps: " << snaps << '\n'
        << "rust-calls: " << rustCalls << '\n'
        << "callback-failure: " << (callbackFailure ? "yes" : "no") << '\n'
        << "retained-target: " << (!dragged.expired() ? "yes" : "no") << '\n'
        << "pending-snap: " << pendingSnap << '\n'
        << "monitor: " << monitorName << '\n';
    for (int i = 0; i < 2; ++i) {
        const auto r = layout.zones[i];
        out << "zone-" << i << ": " << r.x << ' ' << r.y << ' ' << r.w << ' ' << r.h << '\n';
    }
    return out.str();
}
}

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE pluginHandle) {
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("zones-rust-poc: Hyprland ABI mismatch; rebuild against matching headers.");
    handle = pluginHandle;
    auto& events = Event::bus()->m_events;
    listeners.push_back(events.input.mouse.move.listen([](Vector2D point, Event::SCallbackInfo&) {
        guarded([&] { update(point); });
    }));
    listeners.push_back(events.input.mouse.button.listen([](IPointer::SButtonEvent event, Event::SCallbackInfo&) {
        guarded([&] { release(event); if (visible) queueRefresh(); });
    }));
    listeners.push_back(events.input.keyboard.key.listen([](IKeyboard::SKeyEvent event, Event::SCallbackInfo&) {
        guarded([&] {
            if (visible || !dragged.expired() || event.keycode == KEY_LEFTSHIFT || event.keycode == KEY_RIGHTSHIFT) queueRefresh();
            if (event.keycode == KEY_ESC && event.state == WL_KEYBOARD_KEY_STATE_PRESSED && visible) { cancelled = true; hide(); }
        });
    }));
    listeners.push_back(events.render.stage.listen([](eRenderStage stage) { guarded([&] { render(stage); }); }));
    listeners.push_back(events.monitor.layoutChanged.listen([] { guarded(reset); }));
    listeners.push_back(events.config.preReload.listen([] { guarded(reset); }));
    listeners.push_back(g_pSessionLockManager->m_events.lock.listen([] { guarded(reset); }));
    listeners.push_back(events.window.close.listen([](PHLWINDOW window) {
        guarded([&] { if (const auto target = dragged.lock(); target && target->window() == window) reset(); });
    }));
    command = HyprlandAPI::registerHyprCtlCommand(handle, {"zones-rust-poc", true,
        [](eHyprCtlOutputFormat, std::string) { return status(); }});
    return {"zones-rust-poc", "Isolated Rust geometry and native C++ drag adapter evaluation", "Omarchy Zones", "0.1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    guarded(reset);
    listeners.clear();
    if (command) HyprlandAPI::unregisterHyprCtlCommand(handle, command);
    command.reset();
}
