#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/SessionLockManager.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <hyprland/src/render/pass/TexPassElement.hpp>
#include <hyprland/src/render/pass/BorderPassElement.hpp>

#include "profiles.hpp"
#include "theme.hpp"

#include <linux/input-event-codes.h>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <optional>
#include <map>
#include <numbers>
#include <array>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Zone {
    std::string monitor;
    int x, y, width, height;
    bool operator==(const Zone &) const = default;
};
struct MiniZone {
    CBox box;
    Zone zone;
};
struct ProfileCard {
    size_t profile;
    CBox box, thumbnail;
    std::vector<MiniZone> miniZones;
};
struct Picker {
    std::string monitor;
    CBox box;
    std::vector<ProfileCard> cards;
};

HANDLE handle = nullptr;
std::vector<CHyprSignalListener> listeners;
SP<SHyprCtlCommand> statusCommand;
std::vector<Zone> activeZones;
::zones::Profiles profiles;
size_t activeProfile = 0;
std::string lastProfile;
std::vector<Picker> pickers;
std::map<std::string, SP<Render::ITexture>> textTextures;
WP<Layout::ITarget> dragTarget;
std::optional<size_t> hovered;
bool visible = false;
bool cancelled = false;
uint64_t pendingSnap = 0;
uint64_t pendingRefresh = 0;
uint64_t snapCount = 0;
std::string lastError;
// Theme values are snapshots for the current gesture. No theme process or idle
// watcher is needed: configuration reloads and activated drags refresh them.
::zones::theme::Theme theme;
Config::CGradientValueData activeBorder;
Config::CGradientValueData inactiveBorder;
float roundingPower = 2.F;
constexpr size_t maxTextTextures = 512;

CHyprColor color(::zones::theme::Color rgba) {
    return {((rgba >> 24) & 255) / 255.F, ((rgba >> 16) & 255) / 255.F, ((rgba >> 8) & 255) / 255.F,
            (rgba & 255) / 255.F};
}

CHyprColor withOpacity(const CHyprColor &value, double opacity) {
    return value.modifyA(value.a * std::clamp(opacity, 0.0, 1.0));
}

Config::CGradientValueData gradient(const ::zones::theme::Gradient &value) {
    std::vector<CHyprColor> colors;
    colors.reserve(value.colors.size());
    for (const auto stop : value.colors)
        colors.push_back(color(stop));
    if (colors.empty())
        colors.push_back(color(theme.accent));
    return {std::move(colors), static_cast<float>(value.angle * std::numbers::pi / 180.0)};
}

std::filesystem::path xdgPath(const char *variable, const char *fallback) {
    if (const char *value = std::getenv(variable); value && *value)
        return value;
    const char *home = std::getenv("HOME");
    return std::filesystem::path(home ? home : "/tmp") / fallback;
}

std::filesystem::path configPath() {
    return xdgPath("XDG_CONFIG_HOME", ".config") / "omarchy-zones/zones.conf";
}

void selectProfile(size_t index) {
    activeProfile = index;
    activeZones.clear();
    hovered.reset();
    if (index >= profiles.size())
        return;
    for (const auto &[monitor, rectangles] : profiles[index].layouts)
        for (const auto &r : rectangles)
            activeZones.push_back({monitor, r.x, r.y, r.w, r.h});
}

// Opening a FIFO or device from inside the compositor must never block its
// event loop. Read a bounded regular file and let the shared parser validate it.
bool readZoneFile(std::string &contents) {
    const int descriptor = open(configPath().c_str(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (descriptor < 0) {
        lastError = "Open the zone editor and save a profile.";
        return false;
    }
    struct FileDescriptor {
        int value;
        ~FileDescriptor() {
            close(value);
        }
    } file{descriptor};
    struct stat information{};
    if (fstat(descriptor, &information) != 0 || !S_ISREG(information.st_mode) || information.st_size < 0 ||
        information.st_size > static_cast<off_t>(::zones::maxProfileFileBytes)) {
        lastError = "The zone file must be a regular file no larger than 128 KiB.";
        return false;
    }
    std::array<char, 4096> buffer;
    for (;;) {
        const auto count = read(descriptor, buffer.data(), buffer.size());
        if (count < 0) {
            if (errno == EINTR)
                continue;
            lastError = "Cannot read the zone file.";
            return false;
        }
        if (count == 0)
            return true;
        if (static_cast<size_t>(count) > ::zones::maxProfileFileBytes - contents.size()) {
            lastError = "The zone file exceeds 128 KiB.";
            return false;
        }
        contents.append(buffer.data(), static_cast<size_t>(count));
    }
}

bool loadZones() {
    std::string contents;
    ::zones::Profiles incoming;
    const bool readable = readZoneFile(contents);
    std::istringstream input(contents);
    if (!readable || !::zones::readProfiles(input, incoming, lastError)) {
        activeZones.clear();
        profiles.clear();
        hovered.reset();
        activeProfile = 0;
        return false;
    }
    profiles = std::move(incoming);
    size_t selected = 0;
    for (size_t i = 0; i < profiles.size(); ++i)
        if (profiles[i].name == lastProfile)
            selected = i;
    selectProfile(selected);
    lastError.clear();
    return true;
}

void loadTheme() {
    theme = ::zones::theme::load(::zones::theme::directory());
    activeBorder = gradient(theme.activeBorder);
    inactiveBorder = gradient(theme.inactiveBorder);

    // The compositor is authoritative for runtime overrides. Copy the complete
    // gradient, retaining all color stops, alpha values and the native angle.
    static auto configuredActive = CConfigValue<Config::IComplexConfigValue>("general:col.active_border");
    static auto configuredInactive = CConfigValue<Config::IComplexConfigValue>("general:col.inactive_border");
    static auto configuredWidth = CConfigValue<Config::INTEGER>("general:border_size");
    static auto configuredRounding = CConfigValue<Config::INTEGER>("decoration:rounding");
    static auto configuredPower = CConfigValue<Config::FLOAT>("decoration:rounding_power");
    if (configuredActive.good())
        if (const auto value = dynamic_cast<Config::CGradientValueData *>(configuredActive.ptr());
            value && !value->m_colors.empty())
            activeBorder = *value;
    if (configuredInactive.good())
        if (const auto value = dynamic_cast<Config::CGradientValueData *>(configuredInactive.ptr());
            value && !value->m_colors.empty())
            inactiveBorder = *value;
    if (configuredWidth.good())
        theme.borderWidth = std::clamp<double>(*configuredWidth, 0, 32);
    if (configuredRounding.good())
        theme.rounding = std::clamp<double>(*configuredRounding, 0, 128);
    if (configuredPower.good())
        roundingPower = std::clamp<float>(*configuredPower, 1.F, 10.F);
    textTextures.clear();
}

PHLMONITOR monitorFor(const Zone &zone) {
    for (const auto &monitor : State::monitorState()->monitors()) {
        if (monitor->m_name == zone.monitor && zone.x >= monitor->m_reservedArea.left() &&
            zone.y >= monitor->m_reservedArea.top() &&
            zone.x + zone.width <= monitor->m_size.x - monitor->m_reservedArea.right() &&
            zone.y + zone.height <= monitor->m_size.y - monitor->m_reservedArea.bottom())
            return monitor;
    }
    return nullptr;
}

CBox globalBox(const Zone &zone, const PHLMONITOR &monitor) {
    return {monitor->m_position.x + zone.x, monitor->m_position.y + zone.y, static_cast<double>(zone.width),
            static_cast<double>(zone.height)};
}

bool contains(const CBox &box, const Vector2D &point) {
    return point.x >= box.x && point.x < box.x + box.w && point.y >= box.y && point.y < box.y + box.h;
}

// All picker boxes are global logical coordinates, shared by paint and hit testing.
void buildPickers() {
    pickers.clear();
    for (const auto &monitor : State::monitorState()->monitors()) {
        const double usableWidth = monitor->m_size.x - monitor->m_reservedArea.left() - monitor->m_reservedArea.right();
        const double usableHeight =
            monitor->m_size.y - monitor->m_reservedArea.top() - monitor->m_reservedArea.bottom();
        std::vector<size_t> available;
        for (size_t i = 0; i < profiles.size(); ++i) {
            const auto found = profiles[i].layouts.find(monitor->m_name);
            if (found == profiles[i].layouts.end() || found->second.empty())
                continue;
            if (std::ranges::all_of(found->second, [&](const auto &r) {
                    return bool(monitorFor({monitor->m_name, r.x, r.y, r.w, r.h}));
                }))
                available.push_back(i);
        }
        if (available.empty() || usableWidth < 180 || usableHeight < 180)
            continue;
        const int columns = std::min(int(available.size()), std::clamp(int((usableWidth - 44) / 164), 1, 6));
        const int rows = (int(available.size()) + columns - 1) / columns;
        const double cardWidth = std::min(152.0, (usableWidth - 44 - (columns - 1) * 12) / columns);
        const double rowHeight = std::min(112.0, (usableHeight - 100) / rows);
        if (rowHeight < 48)
            continue;
        const double width = 28 + columns * cardWidth + (columns - 1) * 12;
        const double height = 68 + rows * rowHeight;
        Picker picker;
        picker.monitor = monitor->m_name;
        picker.box = {monitor->m_position.x + monitor->m_reservedArea.left() + (usableWidth - width) / 2,
                      monitor->m_position.y + monitor->m_reservedArea.top() + 18, width, height};
        for (size_t n = 0; n < available.size(); ++n) {
            ProfileCard card;
            card.profile = available[n];
            card.box = {picker.box.x + 14 + (n % columns) * (cardWidth + 12),
                        picker.box.y + 40 + (n / columns) * rowHeight, cardWidth, rowHeight - 10};
            card.thumbnail = {card.box.x, card.box.y, cardWidth, card.box.h - 23};
            const double scale =
                std::min((card.thumbnail.w - 10) / monitor->m_size.x, (card.thumbnail.h - 10) / monitor->m_size.y);
            const Vector2D origin{card.thumbnail.x + (card.thumbnail.w - monitor->m_size.x * scale) / 2,
                                  card.thumbnail.y + (card.thumbnail.h - monitor->m_size.y * scale) / 2};
            for (const auto &r : profiles[card.profile].layouts.at(monitor->m_name)) {
                CBox box(origin.x + r.x * scale, origin.y + r.y * scale, r.w * scale, r.h * scale);
                // Preserve tiny zones as real targets; shrink gutters only when there is room.
                const double inset = std::min({1.5, box.w / 8, box.h / 8});
                box.x += inset;
                box.y += inset;
                box.w -= 2 * inset;
                box.h -= 2 * inset;
                card.miniZones.push_back({box, {monitor->m_name, r.x, r.y, r.w, r.h}});
            }
            picker.cards.push_back(std::move(card));
        }
        pickers.push_back(std::move(picker));
    }
}

void damageOverlay() {
    for (const auto &zone : activeZones) {
        // Clear the old overlay even if its zone became invalid after a work-area change.
        for (const auto &monitor : State::monitorState()->monitors())
            if (monitor->m_name == zone.monitor)
                g_pHyprRenderer->damageBox(globalBox(zone, monitor));
    }
    for (const auto &picker : pickers)
        g_pHyprRenderer->damageBox(picker.box);
}

void hideOverlay() {
    if (visible)
        damageOverlay();
    visible = false;
    hovered.reset();
    textTextures.clear();
}

void cancelScheduledWork() {
    if (pendingSnap)
        g_pEventLoopManager->removeDoLater(pendingSnap);
    if (pendingRefresh)
        g_pEventLoopManager->removeDoLater(pendingRefresh);
    pendingSnap = pendingRefresh = 0;
}

void cancelGesture() {
    cancelScheduledWork();
    hideOverlay();
    dragTarget.reset();
    cancelled = true;
}

// Never let an exception in this plugin unwind through Hyprland's event bus.
// Failed gestures lose their transient target and pending snap immediately.
template <typename Callback> void guarded(const char *operation, Callback &&callback) noexcept {
    const auto failed = [&](const char *detail) noexcept {
        // Cancel work before constructing an error string: allocation failure
        // must not leave an earlier drop scheduled for a later idle callback.
        try {
            cancelScheduledWork();
            hideOverlay();
        } catch (...) {
            visible = false;
            hovered.reset();
        }
        dragTarget.reset();
        cancelled = true;
        try {
            lastError = std::string(operation) + ": " + std::string(detail).substr(0, 256);
        } catch (...) {
            // Error reporting is best effort under memory pressure.
        }
    };
    try {
        callback();
    } catch (const std::exception &error) {
        failed(error.what());
    } catch (...) {
        failed("Unexpected plugin error.");
    }
}

bool shiftDown() {
    // Hyprland's modifier mask follows XKB: Shift is bit zero.
    return (g_pInputManager->getModsFromAllKBs() & 1U) != 0;
}

void updateOverlay(const Vector2D &cursor) {
    const auto &controller = g_layoutManager->dragController();
    const auto target = controller->target();
    if (g_pSessionLockManager->isSessionLocked()) {
        hideOverlay();
        dragTarget = target;
        cancelled = true;
        return;
    }
    if (!target || controller->mode() != MBIND_MOVE || target->type() != Layout::TARGET_TYPE_WINDOW ||
        !target->window() || !target->window()->m_isMapped || target->window()->m_group) {
        hideOverlay();
        dragTarget.reset();
        cancelled = false;
        return;
    }
    // KeybindManager clears this flag after dispatching a mouse bind. When the
    // configured threshold is zero, native motion never sets it again.
    static auto threshold = CConfigValue<Config::INTEGER>("binds:drag_threshold");
    if (!shiftDown() || (*threshold > 0 && !controller->dragThresholdReached())) {
        hideOverlay();
        return;
    }
    if (dragTarget.lock() != target) {
        hideOverlay();
        dragTarget = target;
        cancelled = false;
        loadZones();
        loadTheme();
        buildPickers();
    }
    if (cancelled || pickers.empty()) {
        hideOverlay();
        return;
    }
    std::optional<size_t> next;
    bool insidePicker = false;
    bool profileChanged = false;
    for (const auto &picker : pickers) {
        if (!contains(picker.box, cursor))
            continue;
        insidePicker = true;
        for (const auto &card : picker.cards) {
            if (!contains(card.box, cursor))
                continue;
            if (activeProfile != card.profile) {
                damageOverlay();
                selectProfile(card.profile);
                profileChanged = true;
            }
            for (const auto &mini : card.miniZones)
                if (contains(mini.box, cursor))
                    for (size_t i = 0; i < activeZones.size(); ++i)
                        if (activeZones[i] == mini.zone)
                            next = i;
            break;
        }
        break;
    }
    // Tray gutters and labels never fall through to a screen zone behind the tray.
    if (!insidePicker)
        for (size_t i = 0; i < activeZones.size(); ++i)
            if (const auto monitor = monitorFor(activeZones[i]);
                monitor && contains(globalBox(activeZones[i], monitor), cursor)) {
                next = i;
                break;
            }
    if (!visible || next != hovered || profileChanged) {
        visible = true;
        hovered = next;
        damageOverlay();
    }
}

void queueRefresh() {
    if (pendingRefresh)
        return;
    // The keyboard callback precedes Hyprland's modifier update. Run once after it.
    pendingRefresh = g_pEventLoopManager->doLater([] {
        pendingRefresh = 0;
        guarded("Refresh", [] { updateOverlay(g_pInputManager->getMouseCoordsInternal()); });
    });
}

void snapOnce(const WP<Layout::ITarget> &weakTarget, const Zone &zone, const std::string &profileName) {
    const auto target = weakTarget.lock();
    const auto monitor = monitorFor(zone);
    if (g_pSessionLockManager->isSessionLocked() || !target || !monitor ||
        target->type() != Layout::TARGET_TYPE_WINDOW || !target->window() || !target->window()->m_isMapped ||
        target->window()->m_group || g_layoutManager->dragController()->target())
        return;

    const auto minimum = target->minSize();
    const auto maximum = target->maxSize();
    if ((minimum && (zone.width < minimum->x || zone.height < minimum->y)) ||
        (maximum && (zone.width > maximum->x || zone.height > maximum->y))) {
        lastError = "The target window's size limits do not fit this zone.";
        HyprlandAPI::addNotification(handle, "Omarchy Zones: " + lastError, color(theme.accent), 3500.F);
        return;
    }
    const auto workspace =
        monitor->m_activeSpecialWorkspace ? monitor->m_activeSpecialWorkspace : monitor->m_activeWorkspace;
    if (!workspace || !workspace->m_space)
        return;
    if (!target->floating())
        g_layoutManager->changeFloatingMode(target);
    // The normal drag follows the window centre. A drop follows the selected
    // zone's monitor, which can differ while crossing a monitor boundary.
    if (target->workspace() != workspace)
        target->assignToSpace(workspace->m_space);
    target->damageEntire();
    g_layoutManager->setTargetGeom(globalBox(zone, monitor), target);
    target->damageEntire();
    lastError.clear();
    lastProfile = profileName;
    ++snapCount;
}

void onRelease(const IPointer::SButtonEvent &event) {
    if (event.button != BTN_LEFT || event.state != WL_POINTER_BUTTON_STATE_RELEASED)
        return;
    const auto target = dragTarget.lock();
    const auto index = hovered;
    const auto &controller = g_layoutManager->dragController();
    const bool selectionValid = index && *index < activeZones.size() && activeProfile < profiles.size();
    const bool shouldSnap = visible && selectionValid && target && shiftDown() && !cancelled &&
                            !g_pSessionLockManager->isSessionLocked() && controller->mode() == MBIND_MOVE &&
                            controller->target() == target;
    hideOverlay();
    dragTarget.reset();
    cancelled = false;
    if (!shouldSnap)
        return;
    const Zone zone = activeZones[*index];
    const std::string profileName = profiles[activeProfile].name;
    if (pendingSnap)
        g_pEventLoopManager->removeDoLater(pendingSnap);
    const WP<Layout::ITarget> weakTarget = target;
    // Let Hyprland finish its native drag first, including restoring a tiled target.
    // This weak reference lasts one idle callback; no window assignment is stored.
    pendingSnap = g_pEventLoopManager->doLater([weakTarget, zone, profileName] {
        pendingSnap = 0;
        guarded("Snap", [&] { snapOnce(weakTarget, zone, profileName); });
    });
}

void rectangle(const CBox &box, const CHyprColor &color, int round = 0) {
    if (box.w <= 0 || box.h <= 0)
        return;
    CRectPassElement::SRectData data;
    data.box = box;
    data.color = color;
    data.round = round;
    data.roundingPower = roundingPower;
    g_pHyprRenderer->addPassElement(makeUnique<CRectPassElement>(data));
}

CBox physical(const CBox &global, const PHLMONITOR &monitor) {
    return {(global.x - monitor->m_position.x) * monitor->m_scale,
            (global.y - monitor->m_position.y) * monitor->m_scale, global.w * monitor->m_scale,
            global.h * monitor->m_scale};
}

int physicalRadius(const CBox &box, const PHLMONITOR &monitor, double radius) {
    return std::lround(std::min({radius, box.w / 2, box.h / 2}) * monitor->m_scale);
}

void border(const CBox &box, const PHLMONITOR &monitor, const Config::CGradientValueData &colors, double width,
            double radius, double opacity = 1.0) {
    const int logicalWidth = std::lround(width);
    if (logicalWidth <= 0 || colors.m_colors.empty())
        return;
    const int pixels = std::lround(logicalWidth * monitor->m_scale);
    CBox inner = physical(box, monitor);
    inner.x += pixels;
    inner.y += pixels;
    inner.w -= 2 * pixels;
    inner.h -= 2 * pixels;
    if (inner.w <= 0 || inner.h <= 0)
        return;
    CBorderPassElement::SBorderData data;
    data.box = inner;
    data.grad1 = colors;
    data.borderSize = logicalWidth; // Hyprland scales this field internally.
    data.outerRound = physicalRadius(box, monitor, radius);
    data.round = std::max(0, data.outerRound - pixels);
    data.roundingPower = roundingPower;
    data.a = std::clamp(opacity, 0.0, 1.0);
    g_pHyprRenderer->addPassElement(makeUnique<CBorderPassElement>(data));
}

void panel(const CBox &box, const PHLMONITOR &monitor, const CHyprColor &fill, const Config::CGradientValueData &colors,
           double width, double radius) {
    rectangle(physical(box, monitor), fill, physicalRadius(box, monitor, radius));
    border(box, monitor, colors, width, radius);
}

void control(const CBox &box, const PHLMONITOR &monitor, const ::zones::theme::Control &style, double radius) {
    rectangle(physical(box, monitor), color(theme.surface), physicalRadius(box, monitor, radius));
    rectangle(physical(box, monitor), withOpacity(color(style.color), style.fillAlpha),
              physicalRadius(box, monitor, radius));
    border(box, monitor, gradient(style.border), style.borderWidth, radius, style.borderAlpha);
}

void label(const std::string &value, const CBox &box, const PHLMONITOR &monitor, bool centered = false, int size = 12,
           bool inverted = false) {
    if (box.w < 10 || box.h < 10)
        return;
    const int pixels = std::clamp(std::lround(size * theme.fontSize / 12 * monitor->m_scale), 1L, 256L);
    const int maxWidth = std::clamp(std::lround(box.w * monitor->m_scale), 1L, 4096L);
    const std::string key =
        std::to_string(pixels) + ":" + std::to_string(maxWidth) + ":" + std::to_string(inverted) + ":" + value;
    auto found = textTextures.find(key);
    if (found == textTextures.end()) {
        // Allocate only inside a visible render. All plugin-owned textures are
        // released as soon as the activated drag ends, including cancellation.
        if (textTextures.size() >= maxTextTextures)
            return;
        auto texture = g_pHyprRenderer->renderText(value, color(inverted ? theme.background : theme.foreground), pixels,
                                                   false, "monospace", maxWidth);
        found = textTextures.emplace(key, std::move(texture)).first;
    }
    const auto &texture = found->second;
    if (!texture || texture->m_size.x <= 0 || texture->m_size.y <= 0)
        return;
    const auto bounds = physical(box, monitor);
    CTexPassElement::SRenderData data;
    data.tex = texture;
    data.box = {bounds.x + (centered ? (bounds.w - texture->m_size.x) / 2 : 0),
                bounds.y + (bounds.h - texture->m_size.y) / 2, texture->m_size.x, texture->m_size.y};
    data.clipBox = bounds;
    g_pHyprRenderer->addPassElement(makeUnique<CTexPassElement>(data));
}

void render(eRenderStage stage) {
    if (stage != RENDER_LAST_MOMENT || !visible || g_pSessionLockManager->isSessionLocked())
        return;
    const auto monitor = g_pHyprRenderer->renderData().pMonitor.lock();
    if (!monitor)
        return;
    size_t number = 0;
    for (size_t i = 0; i < activeZones.size(); ++i) {
        const auto &zone = activeZones[i];
        if (zone.monitor != monitor->m_name || !monitorFor(zone))
            continue;
        ++number;
        const bool selected = hovered == i;
        const auto full = globalBox(zone, monitor);
        const auto fill = selected ? withOpacity(color(theme.selectionColor), theme.selectionFillAlpha)
                                   : withOpacity(color(theme.normal.color), theme.normal.fillAlpha);
        panel(full, monitor, fill, selected ? activeBorder : inactiveBorder, theme.borderWidth, theme.rounding);
        const double badgeSize = std::min({34.0, full.w, full.h});
        CBox badge(full.x + (full.w - badgeSize) / 2, full.y + (full.h - badgeSize) / 2, badgeSize, badgeSize);
        rectangle(physical(badge, monitor), color(selected ? theme.accent : theme.surface),
                  physicalRadius(badge, monitor, theme.rounding));
        label(std::to_string(number), badge, monitor, true, 16, selected);
    }
    for (const auto &picker : pickers) {
        if (picker.monitor != monitor->m_name)
            continue;
        panel(picker.box, monitor, color(theme.background), activeBorder, theme.borderWidth, theme.rounding);
        label("Zones", {picker.box.x + 14, picker.box.y + 8, 60, 25}, monitor, false, 14);
        label("Super + Shift", {picker.box.x + picker.box.w - 106, picker.box.y + 8, 92, 25}, monitor, true, 11);
        for (const auto &card : picker.cards) {
            if (card.profile >= profiles.size())
                continue;
            const auto &cardStyle = card.profile == activeProfile ? theme.selected : theme.normal;
            control(card.thumbnail, monitor, cardStyle, theme.rounding / 2);
            for (size_t z = 0; z < card.miniZones.size(); ++z) {
                const auto &mini = card.miniZones[z];
                const bool selected = card.profile == activeProfile && hovered && *hovered < activeZones.size() &&
                                      activeZones[*hovered] == mini.zone;
                // The hit target remains its true proportional rectangle even
                // when too small for a readable number; the desktop target is available too.
                rectangle(physical(mini.box, monitor),
                          selected ? color(theme.accent) : withOpacity(color(theme.muted), theme.selectionFillAlpha),
                          physicalRadius(mini.box, monitor, theme.rounding / 4));
                if (mini.box.w >= 14 && mini.box.h >= 16)
                    label(std::to_string(z + 1), mini.box, monitor, true, 10, selected);
            }
            label(profiles[card.profile].name, {card.box.x, card.thumbnail.y + card.thumbnail.h + 3, card.box.w, 20},
                  monitor, true, 11);
        }
        label(picker.box.w < 300 ? "Release to snap" : "Hover a zone · Release to snap",
              {picker.box.x + 14, picker.box.y + picker.box.h - 25, picker.box.w - 28, 20}, monitor, false, 11);
    }
}

std::string status() {
    std::ostringstream output;
    const auto &controller = g_layoutManager->dragController();
    const auto target = controller->target();
    output << "omarchy-zones 0.3.1\n"
           << "profiles: " << profiles.size() << "\n"
           << "profile: " << (activeProfile < profiles.size() ? profiles[activeProfile].name : "none") << "\n"
           << "zones: " << activeZones.size() << "\n"
           << "overlay: " << (visible ? "visible" : "hidden") << "\n"
           << "picker: " << (visible && !pickers.empty() ? "visible" : "hidden") << "\n"
           << "text-textures: " << textTextures.size() << "\n"
           << "pending-snap: " << (pendingSnap ? "yes" : "no") << "\n"
           << "pending-refresh: " << (pendingRefresh ? "yes" : "no") << "\n"
           << "retained-target: " << (!dragTarget.expired() ? "yes" : "no") << "\n"
           << "theme-border: " << activeBorder.toString() << "\n"
           << "theme-border-width: " << theme.borderWidth << "\n"
           << "theme-rounding: " << theme.rounding << "\n"
           << "theme-font-size: " << theme.fontSize << "\n"
           << "target-zone: " << (hovered ? std::to_string(*hovered + 1) : "none") << "\n"
           << "snaps: " << snapCount << "\n"
           << "drag-active: " << (target ? "yes" : "no") << "\n"
           << "drag-mode: " << static_cast<int>(controller->mode()) << "\n"
           << "drag-threshold: " << (controller->dragThresholdReached() ? "reached" : "pending") << "\n"
           << "modifier-mask: " << g_pInputManager->getModsFromAllKBs() << "\n"
           << "drag-target-type: " << (target ? std::to_string(static_cast<int>(target->type())) : "none") << "\n"
           << "drag-window-mapped: " << (target && target->window() && target->window()->m_isMapped ? "yes" : "no")
           << "\n"
           << "drag-window-grouped: " << (target && target->window() && target->window()->m_group ? "yes" : "no")
           << "\n"
           << "config: " << configPath().string() << "\n"
           << "error: " << (lastError.empty() ? "none" : lastError) << "\n";
    return output.str();
}
} // namespace

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE pluginHandle) {
    handle = pluginHandle;
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("omarchy-zones: Hyprland ABI mismatch; rebuild against the running version.");
    loadZones();
    loadTheme();
    auto &events = Event::bus()->m_events;
    listeners.push_back(
        g_pSessionLockManager->m_events.lock.listen([] { guarded("Session lock", [] { cancelGesture(); }); }));
    listeners.push_back(events.input.mouse.move.listen(
        [](Vector2D cursor, Event::SCallbackInfo &) { guarded("Pointer motion", [&] { updateOverlay(cursor); }); }));
    listeners.push_back(events.input.mouse.button.listen([](IPointer::SButtonEvent event, Event::SCallbackInfo &) {
        guarded("Pointer button", [&] {
            onRelease(event);
            if (visible)
                queueRefresh();
        });
    }));
    listeners.push_back(events.input.keyboard.key.listen([](IKeyboard::SKeyEvent event, Event::SCallbackInfo &) {
        guarded("Keyboard", [&] {
            if (visible || !dragTarget.expired() || event.keycode == KEY_LEFTSHIFT || event.keycode == KEY_RIGHTSHIFT)
                queueRefresh();
        });
    }));
    listeners.push_back(
        events.render.stage.listen([](eRenderStage stage) { guarded("Render", [&] { render(stage); }); }));
    listeners.push_back(
        events.monitor.layoutChanged.listen([] { guarded("Monitor layout", [] { cancelGesture(); }); }));
    listeners.push_back(
        events.config.preReload.listen([] { guarded("Configuration reload", [] { cancelGesture(); }); }));
    listeners.push_back(events.config.reloaded.listen([] { guarded("Theme reload", [] { loadTheme(); }); }));
    listeners.push_back(events.window.close.listen([](PHLWINDOW window) {
        guarded("Window close", [&] {
            if (const auto target = dragTarget.lock(); target && target->window() == window)
                cancelGesture();
        });
    }));
    statusCommand = HyprlandAPI::registerHyprCtlCommand(
        handle, {"zones", true, [](eHyprCtlOutputFormat, std::string) { return status(); }});
    return {"omarchy-zones", "One-shot, event-driven desktop window zones", "Omarchy Zones contributors", "0.3.1"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    // Cancel callbacks before unloading any code or releasing renderer resources.
    cancelScheduledWork();
    listeners.clear();
    guarded("Unload", [] { hideOverlay(); });
    dragTarget.reset();
    activeZones.clear();
    profiles.clear();
    pickers.clear();
    textTextures.clear();
    if (statusCommand)
        HyprlandAPI::unregisterHyprCtlCommand(handle, statusCommand);
    statusCommand.reset();
    handle = nullptr;
}
