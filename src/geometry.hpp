#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <utility>
#include <vector>

namespace zones {
constexpr int minimumExtent = 32;
struct Rect {
    int x = 0, y = 0, w = 0, h = 0;
    std::int64_t right() const { return std::int64_t{x} + w; }
    std::int64_t bottom() const { return std::int64_t{y} + h; }
    bool operator==(const Rect&) const = default;
};
enum class Edge { Left, Right, Top, Bottom };

inline bool overlaps(std::int64_t a, std::int64_t b, std::int64_t c, std::int64_t d) { return a < d && c < b; }
inline bool overlaps(const Rect& a, const Rect& b) {
    return overlaps(a.x, a.right(), b.x, b.right()) && overlaps(a.y, a.bottom(), b.y, b.bottom());
}
inline bool valid(const std::vector<Rect>& rectangles, const Rect& bounds) {
    if (bounds.w < 0 || bounds.h < 0) return false;
    for (std::size_t i = 0; i < rectangles.size(); ++i) {
        const auto& r = rectangles[i];
        if (r.w < minimumExtent || r.h < minimumExtent || r.x < bounds.x || r.y < bounds.y ||
            r.right() > bounds.right() || r.bottom() > bounds.bottom())
            return false;
        for (std::size_t j = 0; j < i; ++j)
            if (overlaps(r, rectangles[j])) return false;
    }
    return true;
}

// All touching segments of a shared boundary move in one transaction. This
// also handles a long zone abutting several short zones at a T junction.
inline bool moveBoundary(std::vector<Rect>& rectangles, std::size_t selected, Edge edge,
                         std::int64_t position, const Rect& bounds) {
    if (selected >= rectangles.size() || bounds.w < 0 || bounds.h < 0 ||
        position < std::numeric_limits<int>::min() || position > std::numeric_limits<int>::max()) return false;
    if (edge != Edge::Left && edge != Edge::Right && edge != Edge::Top && edge != Edge::Bottom) return false;
    const auto& original = rectangles[selected];
    const bool vertical = edge == Edge::Left || edge == Edge::Right;
    const std::int64_t coordinate = edge == Edge::Left ? original.x : edge == Edge::Right ? original.right()
        : edge == Edge::Top ? original.y : original.bottom();
    if (position == coordinate) return valid(rectangles, bounds);
    if (position < (vertical ? bounds.x : bounds.y) ||
        position > (vertical ? bounds.right() : bounds.bottom())) return false;

    std::vector<bool> included(rectangles.size(), false);
    included[selected] = true;
    bool changed = true;
    while (changed) {
        changed = false;
        for (std::size_t i = 0; i < rectangles.size(); ++i) {
            if (included[i]) continue;
            const auto& candidate = rectangles[i];
            const bool hasEdge = vertical ? candidate.x == coordinate || candidate.right() == coordinate
                                          : candidate.y == coordinate || candidate.bottom() == coordinate;
            if (!hasEdge) continue;
            for (std::size_t j = 0; j < rectangles.size(); ++j) {
                if (!included[j]) continue;
                const auto& current = rectangles[j];
                if (vertical ? overlaps(candidate.y, candidate.bottom(), current.y, current.bottom())
                             : overlaps(candidate.x, candidate.right(), current.x, current.right())) {
                    included[i] = true;
                    changed = true;
                    break;
                }
            }
        }
    }

    auto proposed = rectangles;
    for (std::size_t i = 0; i < proposed.size(); ++i) {
        if (!included[i]) continue;
        auto& r = proposed[i];
        // Keep subtraction wide too: two individually valid int coordinates
        // can have a distance larger than an int can represent.
        const bool movingStart = vertical ? r.x == coordinate : r.y == coordinate;
        const std::int64_t extent = vertical
            ? (movingStart ? r.right() - position : position - r.x)
            : (movingStart ? r.bottom() - position : position - r.y);
        if (extent < minimumExtent || extent > std::numeric_limits<int>::max()) return false;
        if (vertical) {
            r.w = static_cast<int>(extent);
            if (movingStart) r.x = static_cast<int>(position);
        } else {
            r.h = static_cast<int>(extent);
            if (movingStart) r.y = static_cast<int>(position);
        }
    }
    if (!valid(proposed, bounds)) return false;
    rectangles = std::move(proposed);
    return true;
}

inline bool move(std::vector<Rect>& rectangles, std::size_t selected, int x, int y, const Rect& bounds) {
    if (selected >= rectangles.size()) return false;
    auto proposed = rectangles;
    proposed[selected].x = x;
    proposed[selected].y = y;
    if (!valid(proposed, bounds)) return false;
    rectangles = std::move(proposed);
    return true;
}
} // namespace zones
