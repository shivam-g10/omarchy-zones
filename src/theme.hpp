#pragma once

#include <toml++/toml.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

// Shared theme values contain no Qt or compositor objects. Each renderer adapts
// these values to its own color/gradient types and supplies live border options.
namespace zones::theme {
using Color = std::uint32_t; // RRGGBBAA, including alpha.
struct Gradient {
    std::vector<Color> colors;
    double angle = 0;
    bool operator==(const Gradient&) const = default;
};
struct Control {
    Color color = 0xf4f7faff;
    double fillAlpha = .04;
    Gradient border{{0xf4f7faff}, 0};
    double borderAlpha = .4;
    double borderWidth = 1;
};
struct Theme {
    Color background = 0x0b1420ff, surface = 0x07101aff, raised = 0x132334ff;
    Color foreground = 0xf4f7faff, muted = 0x70869cff, accent = 0x67d4e8ff, error = 0xf07178ff;
    Gradient activeBorder{{accent}, 0}, inactiveBorder{{muted}, 0};
    double borderWidth = 2, rounding = 10, fontSize = 12;
    double pressedFillAlpha = .22, selectionFillAlpha = .35;
    Color pressedColor = foreground, selectionColor = foreground;
    Control normal, hover, focus, selected;
};

inline std::filesystem::path directory() {
    if (const char* state = std::getenv("XDG_STATE_HOME"); state && *state)
        return std::filesystem::path(state) / "omarchy/current/theme";
    const char* home = std::getenv("HOME");
    return std::filesystem::path(home ? home : "") / ".local/state/omarchy/current/theme";
}

inline std::string_view trim(std::string_view value) {
    const auto start = value.find_first_not_of(" \t\r\n");
    if (start == std::string_view::npos) return {};
    return value.substr(start, value.find_last_not_of(" \t\r\n") - start + 1);
}

inline std::optional<Color> parseColor(std::string_view value) {
    value = trim(value);
    bool alpha = false;
    if (value.starts_with('#')) {
        value.remove_prefix(1);
        alpha = value.size() == 4 || value.size() == 8;
    } else if (value.starts_with("rgba(") && value.ends_with(')')) {
        value = value.substr(5, value.size() - 6);
        if (value.size() != 8) return {};
        alpha = true;
    } else if (value.starts_with("rgb(") && value.ends_with(')')) {
        value = value.substr(4, value.size() - 5);
        if (value.size() != 6) return {};
    } else return {};
    if (value.size() != 3 && value.size() != 4 && value.size() != 6 && value.size() != 8) return {};
    Color parsed = 0;
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed, 16);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size()) return {};
    if (value.size() <= 4) {
        Color expanded = 0;
        for (std::size_t i = 0; i < value.size(); ++i) {
            const auto nibble = (parsed >> ((value.size() - i - 1) * 4)) & 15;
            expanded = (expanded << 8) | (nibble * 17);
        }
        parsed = expanded;
    }
    return alpha ? parsed : (parsed << 8) | 255;
}

inline std::optional<Gradient> parseGradient(std::string_view value, bool hyprctlArgb = false) {
    Gradient gradient;
    value = trim(value);
    while (!value.empty()) {
        const auto end = value.find_first_of(" \t\r\n");
        auto token = value.substr(0, end);
        value = end == std::string_view::npos ? std::string_view{} : trim(value.substr(end));
        if (token.ends_with("deg")) {
            if (!value.empty()) return {};
            token.remove_suffix(3);
            double angle = 0;
            const auto parsed = std::from_chars(token.data(), token.data() + token.size(), angle);
            if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size() || !std::isfinite(angle)) return {};
            gradient.angle = std::fmod(angle, 360.);
        } else {
            std::optional<Color> color;
            if (hyprctlArgb && token.size() == 8) {
                Color argb = 0;
                const auto parsed = std::from_chars(token.data(), token.data() + token.size(), argb, 16);
                if (parsed.ec == std::errc{} && parsed.ptr == token.data() + token.size())
                    color = (argb << 8) | (argb >> 24);
            } else color = parseColor(token);
            if (!color || gradient.colors.size() >= 32) return {};
            gradient.colors.push_back(*color);
        }
    }
    return gradient.colors.empty() ? std::nullopt : std::optional{std::move(gradient)};
}

namespace detail {
inline constexpr std::size_t maxThemeBytes = 128 * 1024;

// O_NONBLOCK prevents a FIFO from stalling the compositor before fstat can
// reject it. Read the opened descriptor, so a path replacement cannot evade
// either the regular-file requirement or the allocation limit.
inline std::optional<std::string> readFile(const std::filesystem::path& path) {
    const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return {};
    struct Descriptor {
        int value;
        ~Descriptor() { ::close(value); }
    } descriptor{fd};
    struct stat metadata{};
    if (::fstat(fd, &metadata) != 0 || !S_ISREG(metadata.st_mode) || metadata.st_size < 0 ||
        static_cast<std::uintmax_t>(metadata.st_size) > maxThemeBytes) return {};
    std::string bytes;
    bytes.reserve(static_cast<std::size_t>(metadata.st_size));
    std::array<char, 4096> buffer;
    while (true) {
        const auto count = ::read(fd, buffer.data(), buffer.size());
        if (count < 0) {
            if (errno == EINTR) continue;
            return {};
        }
        if (count == 0) return bytes;
        if (static_cast<std::size_t>(count) > maxThemeBytes - bytes.size()) return {};
        bytes.append(buffer.data(), static_cast<std::size_t>(count));
    }
}

inline toml::table readTable(const std::filesystem::path& path) {
    auto bytes = readFile(path);
    if (!bytes) return {};
    try { return toml::parse(*bytes); }
    catch (const toml::parse_error&) { return {}; }
}
inline std::string text(const toml::table& table, std::string_view name) {
    return table[name].value_or(std::string{});
}
inline Color color(const toml::table& table, std::string_view name, Color fallback) {
    return parseColor(text(table, name)).value_or(fallback);
}
inline Color stateColor(std::string value, const Theme& theme, Color fallback) {
    const auto parsed = parseColor(value);
    if (parsed) return *parsed;
    value = trim(value);
    std::ranges::transform(value, value.begin(), [](unsigned char c) { return std::tolower(c); });
    if (value == "foreground" || value == "text") return theme.foreground;
    if (value == "accent") return theme.accent;
    if (value == "urgent") return theme.error;
    if (value == "background") return theme.background;
    if (value == "transparent") return 0;
    return fallback; // Includes the shell's inherit/hover aliases for focus.
}
inline double number(const toml::table& table, std::string_view name, double fallback, double low, double high) {
    const double value = table[name].value_or(fallback);
    return std::isfinite(value) ? std::clamp(value, low, high) : fallback;
}
inline Gradient gradient(const toml::table& table, std::string_view name, const Gradient& fallback, const Theme& theme) {
    const auto value = text(table, name);
    if (value == "hyprland.active-border" || value == "hyprland.active-border-foreground") return theme.activeBorder;
    return parseGradient(value).value_or(fallback);
}
inline Control control(const toml::table& table, std::string_view state, const Theme& theme,
                       const Control& fallback) {
    const std::string prefix = std::string(state) + '-';
    const auto color = stateColor(text(table, prefix + "color"), theme, fallback.color);
    auto border = gradient(table, prefix + "border", fallback.border, theme);
    const auto rawBorder = text(table, prefix + "border");
    if (!rawBorder.empty() && !parseGradient(rawBorder) && !rawBorder.starts_with("hyprland."))
        border = {{stateColor(rawBorder, theme, color)}, 0};
    return {color, number(table, prefix + "fill-alpha", fallback.fillAlpha, 0, 1), std::move(border),
            number(table, prefix + "border-alpha", fallback.borderAlpha, 0, 1),
            number(table, prefix + "border-width", fallback.borderWidth, 0, 16)};
}
} // namespace detail

inline Theme load(const std::filesystem::path& themeDirectory = directory()) {
    Theme result;
    const auto colors = detail::readTable(themeDirectory / "colors.toml");
    const auto shell = detail::readTable(themeDirectory / "shell.toml");
    result.background = detail::color(colors, "background", result.background);
    result.foreground = detail::color(colors, "foreground", result.foreground);
    result.surface = detail::color(colors, "dark_background", result.background);
    result.raised = detail::color(colors, "lighter_background", result.background);
    result.accent = detail::color(colors, "accent", result.foreground);
    result.muted = detail::color(colors, "muted", result.foreground);
    result.error = detail::color(colors, "red", result.accent);
    result.activeBorder = parseGradient(detail::text(colors, "hyprland_active_border")).value_or(Gradient{{result.accent}, 0});
    result.inactiveBorder = parseGradient(detail::text(colors, "hyprland_inactive_border")).value_or(Gradient{{result.muted}, 0});
    if (const auto* hyprland = shell["hyprland"].as_table())
        result.activeBorder = parseGradient(detail::text(*hyprland, "active-border")).value_or(result.activeBorder);
    if (const auto* font = shell["font"].as_table())
        result.fontSize = detail::number(*font, "base-size", result.fontSize, 8, 48);
    const toml::table empty;
    const auto* controls = shell["controls"].as_table();
    if (!controls) controls = &empty;
    result.normal = detail::control(*controls, "normal", result, {result.foreground, .04, {{result.foreground}, 0}, .4, 1});
    result.hover = detail::control(*controls, "hover-cursor", result, {result.foreground, .08, {{result.foreground}, 0}, .25, result.normal.borderWidth});
    result.focus = detail::control(*controls, "focus", result, result.hover);
    result.selected = detail::control(*controls, "selected", result, {result.foreground, .18, {{result.foreground}, 0}, 1, 0});
    result.pressedColor = detail::stateColor(detail::text(*controls, "pressed-color"), result, result.hover.color);
    result.selectionColor = detail::stateColor(detail::text(*controls, "selection-color"), result, result.foreground);
    result.pressedFillAlpha = detail::number(*controls, "pressed-fill-alpha", .22, 0, 1);
    result.selectionFillAlpha = detail::number(*controls, "selection-fill-alpha", .35, 0, 1);
    return result;
}
} // namespace zones::theme
