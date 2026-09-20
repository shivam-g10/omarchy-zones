#include "geometry.hpp"
#include <cassert>
#include <iostream>
#include <climits>

int main() {
    using namespace zones;
    const Rect bounds{0, 0, 1000, 800};
    std::vector<Rect> rectangles{{0, 0, 500, 800}, {500, 0, 500, 800}};
    assert(moveBoundary(rectangles, 0, Edge::Right, 620, bounds));
    assert((rectangles[0] == Rect{0, 0, 620, 800}));
    assert((rectangles[1] == Rect{620, 0, 380, 800}));
    auto saved = rectangles;
    assert(!moveBoundary(rectangles, 0, Edge::Right, 990, bounds));
    assert(rectangles == saved);
    assert(!move(rectangles, 0, 100, 0, bounds));
    assert(rectangles == saved);

    rectangles = {{0, 0, 500, 800}, {500, 0, 500, 400}, {500, 400, 500, 400}};
    assert(moveBoundary(rectangles, 1, Edge::Left, 600, bounds));
    assert((rectangles[0] == Rect{0, 0, 600, 800}));
    assert((rectangles[1] == Rect{600, 0, 400, 400}));
    assert((rectangles[2] == Rect{600, 400, 400, 400}));
    assert(valid(rectangles, bounds));

    // A partial shared edge must not create an overlap with a third zone.
    rectangles = {{0, 0, 500, 400}, {500, 0, 500, 800}, {0, 400, 500, 400}};
    assert(moveBoundary(rectangles, 0, Edge::Right, 450, bounds));
    assert((rectangles[2] == Rect{0, 400, 450, 400}));

    rectangles = {{0, 0, 1000, 400}, {0, 400, 1000, 400}};
    assert(moveBoundary(rectangles, 1, Edge::Top, 500, bounds));
    assert((rectangles[0] == Rect{0, 0, 1000, 500}));
    assert((rectangles[1] == Rect{0, 500, 1000, 300}));
    assert(!valid({{0, 0, 600, 800}, {500, 0, 500, 800}}, bounds));
    assert(!valid({{0, 0, 0, 800}}, bounds));
    assert(!valid({{900, 0, 2147483647, 800}}, bounds));
    // Malformed/extreme inputs must not overflow even before validation.
    const Rect extreme{INT_MAX - 1, INT_MAX - 1, INT_MAX, INT_MAX};
    assert(extreme.right() == std::int64_t{INT_MAX} * 2 - 1);
    assert(extreme.bottom() == std::int64_t{INT_MAX} * 2 - 1);
    assert(overlaps(extreme, extreme));
    assert(!valid({extreme, extreme}, bounds));
    assert(!valid({}, {0, 0, -1, 800}));
    rectangles = {{INT_MIN, 0, 32, 100}, {INT_MAX - 32, 0, 32, 100}};
    saved = rectangles;
    assert(!moveBoundary(rectangles, 0, Edge::Right, INT_MAX, {INT_MIN, 0, INT_MAX, 800}));
    assert(rectangles == saved);
    assert(!moveBoundary(rectangles, 0, Edge::Right, std::int64_t{INT_MAX} + 1, bounds));
    assert(rectangles == saved);
    rectangles = {{0, 0, 32, 100}};
    saved = rectangles;
    assert(!moveBoundary(rectangles, 0, Edge::Left, INT_MIN, {INT_MIN, 0, INT_MAX, 800}));
    assert(rectangles == saved);
    rectangles = {extreme};
    saved = rectangles;
    assert(!moveBoundary(rectangles, 0, Edge::Left, 0, bounds));
    assert(rectangles == saved);
    // A display shrink can still be repaired by reducing an oversized zone.
    rectangles = {{0, 0, 1200, 800}};
    assert(moveBoundary(rectangles, 0, Edge::Right, 1000, bounds));
    assert((rectangles[0] == bounds));
    std::cout << "Shared boundaries, T junctions, collision rejection, and atomic rollback passed.\n";
}
