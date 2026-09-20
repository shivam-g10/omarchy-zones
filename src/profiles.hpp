#pragma once

#include "geometry.hpp"
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <istream>
#include <locale>
#include <map>
#include <ostream>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace zones {
using Layouts = std::map<std::string, std::vector<Rect>>;
struct Profile {
    std::string name;
    Layouts layouts;
    bool operator==(const Profile&) const = default;
};
using Profiles = std::vector<Profile>;

inline constexpr std::size_t maxProfiles = 12;
inline constexpr std::size_t maxZonesPerProfile = 64;
inline constexpr std::size_t maxProfileNameBytes = 64;
inline constexpr std::size_t maxProfileFileBytes = 131072;
inline constexpr std::size_t maxProfileLineBytes = 512;

namespace profile_detail {
inline constexpr int coordinateLimit = 32768;
inline constexpr std::size_t maxMonitorNameBytes = 128;

inline bool unicodeSpace(std::uint32_t c) {
    return (c >= 0x09 && c <= 0x0D) || c == 0x20 || c == 0x85 || c == 0xA0 ||
        c == 0x1680 || (c >= 0x2000 && c <= 0x200A) || c == 0x2028 || c == 0x2029 ||
        c == 0x202F || c == 0x205F || c == 0x3000;
}

inline bool control(std::uint32_t c) {
    return c < 0x20 || (c >= 0x7F && c <= 0x9F) || c == 0x2028 || c == 0x2029;
}

// Validate UTF-8 without a locale dependency, preserving names in any language.
inline bool decodeUtf8(std::string_view text, std::vector<std::uint32_t>& points) {
    for (std::size_t i = 0; i < text.size();) {
        const auto first = static_cast<unsigned char>(text[i++]);
        std::uint32_t value = first;
        int continuation = 0;
        std::uint32_t minimum = 0;
        if (first <= 0x7F) {
            // ASCII is already decoded.
        } else if (first >= 0xC2 && first <= 0xDF) {
            value = first & 0x1F; continuation = 1; minimum = 0x80;
        } else if (first >= 0xE0 && first <= 0xEF) {
            value = first & 0x0F; continuation = 2; minimum = 0x800;
        } else if (first >= 0xF0 && first <= 0xF4) {
            value = first & 0x07; continuation = 3; minimum = 0x10000;
        } else return false;
        if (text.size() - i < static_cast<std::size_t>(continuation)) return false;
        for (int j = 0; j < continuation; ++j) {
            const auto next = static_cast<unsigned char>(text[i++]);
            if ((next & 0xC0) != 0x80) return false;
            value = (value << 6) | (next & 0x3F);
        }
        if (value < minimum || value > 0x10FFFF || (value >= 0xD800 && value <= 0xDFFF)) return false;
        points.push_back(value);
    }
    return true;
}

inline bool validProfileName(const std::string& name) {
    if (name.empty() || name.size() > maxProfileNameBytes) return false;
    std::vector<std::uint32_t> points;
    if (!decodeUtf8(name, points) || unicodeSpace(points.front()) || unicodeSpace(points.back())) return false;
    for (const auto c : points)
        if (control(c)) return false;
    return true;
}

inline bool validMonitorName(const std::string& name) {
    if (name.empty() || name.size() > maxMonitorNameBytes || name.front() == '#') return false;
    std::vector<std::uint32_t> points;
    if (!decodeUtf8(name, points)) return false;
    for (const auto c : points)
        if (control(c) || unicodeSpace(c)) return false;
    return true;
}

inline bool integer(const std::string& token, int& result) {
    std::string_view digits = token;
    if (!digits.empty() && digits.front() == '+') {
        digits.remove_prefix(1);
        if (!digits.empty() && digits.front() == '-') return false;
    }
    if (digits.empty()) return false;
    int value = 0;
    const auto parsed = std::from_chars(digits.data(), digits.data() + digits.size(), value, 10);
    if (parsed.ec != std::errc{} || parsed.ptr != digits.data() + digits.size()) return false;
    result = value;
    return true;
}

enum class LineResult { Line, End, Error };

// Read at most one bounded line. The file limit applies to comments and blank
// lines too, and is enforced before untrusted input can grow an allocation.
inline LineResult readLine(std::istream& input, std::string& line, std::size_t& bytes, std::string& error) {
    line.clear();
    char character = 0;
    while (input.get(character)) {
        if (++bytes > maxProfileFileBytes) {
            error = "The zone file exceeds 128 KiB.";
            return LineResult::Error;
        }
        if (character == '\n') return LineResult::Line;
        if (line.size() >= maxProfileLineBytes) {
            error = "A zone file line exceeds 512 bytes.";
            return LineResult::Error;
        }
        line.push_back(character);
    }
    if (input.bad() || !input.eof()) {
        error = "Cannot read the zone file.";
        return LineResult::Error;
    }
    return line.empty() ? LineResult::End : LineResult::Line;
}
} // namespace profile_detail

inline bool validateProfiles(const Profiles& profiles, std::string& error) {
    error.clear();
    if (profiles.empty() || profiles.size() > maxProfiles) {
        error = "Keep between 1 and 12 profiles.";
        return false;
    }
    std::set<std::string> names;
    for (const auto& profile : profiles) {
        if (!profile_detail::validProfileName(profile.name)) {
            error = "Profile names must be valid UTF-8, trimmed, nonempty, at most 64 bytes, and contain no control characters.";
            return false;
        }
        if (!names.insert(profile.name).second) {
            error = "Profile names must be unique: " + profile.name + ".";
            return false;
        }
        std::size_t count = 0;
        for (const auto& [monitor, rectangles] : profile.layouts) {
            if (!profile_detail::validMonitorName(monitor)) {
                error = "Invalid monitor name in profile " + profile.name + ".";
                return false;
            }
            if (rectangles.size() > maxZonesPerProfile - count) {
                error = "At most 64 zones are allowed in each profile.";
                return false;
            }
            count += rectangles.size();
            // Bound coordinates before geometry reaches the compositor. The
            // geometry helpers also use wide arithmetic for malformed inputs.
            for (const auto& rectangle : rectangles) {
                if (rectangle.x < 0 || rectangle.y < 0 || rectangle.x > profile_detail::coordinateLimit ||
                    rectangle.y > profile_detail::coordinateLimit || rectangle.w < minimumExtent ||
                    rectangle.h < minimumExtent || rectangle.w > profile_detail::coordinateLimit - rectangle.x ||
                    rectangle.h > profile_detail::coordinateLimit - rectangle.y) {
                    error = "Zones must be at least 32 by 32 pixels and stay within 0 to 32768 on " + monitor + ".";
                    return false;
                }
            }
            for (std::size_t i = 0; i < rectangles.size(); ++i)
                for (std::size_t j = 0; j < i; ++j)
                    if (overlaps(rectangles[i], rectangles[j])) {
                        error = "Zones overlap in profile " + profile.name + " on " + monitor + ".";
                        return false;
                    }
        }
    }
    return true;
}

inline bool readProfiles(std::istream& input, Profiles& profiles, std::string& error, bool* legacy = nullptr) {
    error.clear();
    Profiles incoming;
    std::size_t bytes = 0, lineNumber = 1, zoneCount = 0;
    std::string line;
    try {
        const auto header = profile_detail::readLine(input, line, bytes, error);
        if (header == profile_detail::LineResult::Error) return false;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const bool oldFormat = line == "omarchy-zones-v1";
        if (header != profile_detail::LineResult::Line || (!oldFormat && line != "omarchy-zones-v2")) {
            error = "Unknown zone file format.";
            return false;
        }
        if (oldFormat) incoming.push_back({"Default", {}});
        while (true) {
            const auto result = profile_detail::readLine(input, line, bytes, error);
            if (result == profile_detail::LineResult::Error) return false;
            if (result == profile_detail::LineResult::End) break;
            ++lineNumber;
            const auto first = line.find_first_not_of(" \t\r\n\v\f");
            if (first == std::string::npos || line[first] == '#') continue;
            auto invalid = [&](const std::string& reason) {
                error = reason + " at line " + std::to_string(lineNumber) + ".";
                return false;
            };
            std::istringstream row(line);
            row.imbue(std::locale::classic());
            std::string monitor;
            row >> monitor;
            row >> std::ws;
            // A monitor named "profile" remains a valid monitor record.
            if (!oldFormat && monitor == "profile" && row.peek() == '"') {
                std::string name, extra;
                if (!(row >> std::quoted(name)) || (row >> extra)) return invalid("Malformed profile name");
                if (incoming.size() >= maxProfiles) return invalid("At most 12 profiles are allowed");
                incoming.push_back({std::move(name), {}});
                zoneCount = 0;
                continue;
            }
            if (incoming.empty()) return invalid("Define a profile before its zones");
            std::string x, y, width, height, extra;
            Rect rectangle;
            if (!(row >> x >> y >> width >> height) || (row >> extra) ||
                !profile_detail::integer(x, rectangle.x) || !profile_detail::integer(y, rectangle.y) ||
                !profile_detail::integer(width, rectangle.w) || !profile_detail::integer(height, rectangle.h))
                return invalid("Invalid zone");
            if (++zoneCount > maxZonesPerProfile) return invalid("At most 64 zones are allowed in each profile");
            incoming.back().layouts[monitor].push_back(rectangle);
        }
        if (!validateProfiles(incoming, error)) return false;
        profiles = std::move(incoming);
        if (legacy) *legacy = oldFormat;
        return true;
    } catch (const std::ios_base::failure&) {
        error = "Cannot read the zone file.";
        return false;
    }
}

inline bool writeProfiles(std::ostream& output, const Profiles& profiles, std::string& error) {
    if (!validateProfiles(profiles, error)) return false;
    std::ostringstream serialized;
    serialized.imbue(std::locale::classic());
    serialized << "omarchy-zones-v2\n";
    for (const auto& profile : profiles) {
        serialized << "profile " << std::quoted(profile.name) << '\n';
        for (const auto& [monitor, rectangles] : profile.layouts)
            for (const auto& rectangle : rectangles)
                serialized << monitor << ' ' << rectangle.x << ' ' << rectangle.y << ' '
                    << rectangle.w << ' ' << rectangle.h << '\n';
    }
    const auto contents = serialized.str();
    if (contents.size() > maxProfileFileBytes) {
        error = "The zone file exceeds 128 KiB.";
        return false;
    }
    try {
        output.write(contents.data(), static_cast<std::streamsize>(contents.size()));
        if (!output) {
            error = "Cannot write the zone file.";
            return false;
        }
    } catch (const std::ios_base::failure&) {
        error = "Cannot write the zone file.";
        return false;
    }
    return true;
}
} // namespace zones
