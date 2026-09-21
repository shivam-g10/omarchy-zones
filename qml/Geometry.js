.pragma library

var minimumExtent = 32

function integer(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value
        && value >= -2147483648 && value <= 2147483647
}

function rectangle(value) {
    return value && integer(value.x) && integer(value.y) && integer(value.w) && integer(value.h)
}

function clone(rectangles) {
    return rectangles.map(function(r) { return {x: r.x, y: r.y, w: r.w, h: r.h} })
}

function intersects(a, b, c, d) { return a < d && c < b }

function overlaps(a, b) {
    return intersects(a.x, a.x + a.w, b.x, b.x + b.w)
        && intersects(a.y, a.y + a.h, b.y, b.y + b.h)
}

function valid(rectangles, bounds) {
    if (!Array.isArray(rectangles) || !rectangle(bounds) || bounds.w < 0 || bounds.h < 0)
        return false
    for (var i = 0; i < rectangles.length; i++) {
        var r = rectangles[i]
        if (!rectangle(r) || r.w < minimumExtent || r.h < minimumExtent
                || r.x < bounds.x || r.y < bounds.y
                || r.x + r.w > bounds.x + bounds.w || r.y + r.h > bounds.y + bounds.h)
            return false
        for (var j = 0; j < i; j++)
            if (overlaps(r, rectangles[j])) return false
    }
    return true
}

function move(rectangles, selected, x, y, bounds) {
    if (!Array.isArray(rectangles) || !integer(selected) || selected < 0
            || selected >= rectangles.length || !integer(x) || !integer(y)) return null
    for (var i = 0; i < rectangles.length; i++)
        if (!rectangle(rectangles[i])) return null
    var proposed = clone(rectangles)
    proposed[selected].x = x
    proposed[selected].y = y
    return valid(proposed, bounds) ? proposed : null
}

// Move the complete connected boundary, including both sides of T junctions.
// All work happens on a copy; an invalid proposal cannot partially resize zones.
function moveBoundary(rectangles, selected, edge, position, bounds) {
    if (!Array.isArray(rectangles) || !integer(selected) || selected < 0
            || selected >= rectangles.length || !rectangle(bounds)
            || bounds.w < 0 || bounds.h < 0 || !integer(position)
            || ["left", "right", "top", "bottom"].indexOf(edge) < 0)
        return null
    for (var r = 0; r < rectangles.length; r++)
        if (!rectangle(rectangles[r])) return null
    var original = rectangles[selected]
    var vertical = edge === "left" || edge === "right"
    var coordinate = edge === "left" ? original.x : edge === "right" ? original.x + original.w
        : edge === "top" ? original.y : original.y + original.h
    if (position === coordinate) return valid(rectangles, bounds) ? clone(rectangles) : null
    if (position < (vertical ? bounds.x : bounds.y)
            || position > (vertical ? bounds.x + bounds.w : bounds.y + bounds.h)) return null
    var included = rectangles.map(function() { return false })
    included[selected] = true
    var changed = true
    while (changed) {
        changed = false
        for (var i = 0; i < rectangles.length; i++) {
            if (included[i]) continue
            var candidate = rectangles[i]
            var touches = vertical ? candidate.x === coordinate || candidate.x + candidate.w === coordinate
                : candidate.y === coordinate || candidate.y + candidate.h === coordinate
            if (!touches) continue
            for (var j = 0; j < rectangles.length; j++) {
                if (!included[j]) continue
                var current = rectangles[j]
                if (vertical ? intersects(candidate.y, candidate.y + candidate.h, current.y, current.y + current.h)
                             : intersects(candidate.x, candidate.x + candidate.w, current.x, current.x + current.w)) {
                    included[i] = true
                    changed = true
                    break
                }
            }
        }
    }
    var proposed = clone(rectangles)
    for (var n = 0; n < proposed.length; n++) {
        if (!included[n]) continue
        var zone = proposed[n]
        var movingStart = vertical ? zone.x === coordinate : zone.y === coordinate
        var extent = vertical ? (movingStart ? zone.x + zone.w - position : position - zone.x)
            : (movingStart ? zone.y + zone.h - position : position - zone.y)
        if (!integer(extent) || extent < minimumExtent) return null
        if (vertical) {
            zone.w = extent
            if (movingStart) zone.x = position
        } else {
            zone.h = extent
            if (movingStart) zone.y = position
        }
    }
    return valid(proposed, bounds) ? proposed : null
}
