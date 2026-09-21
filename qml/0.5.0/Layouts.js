.pragma library

// Picker coordinates are logical pixels relative to the usable monitor origin.
function dimension(value) {
    var n = Number(value)
    return isFinite(n) ? Math.max(8, Math.min(32768, Math.floor(n))) : 8
}

function contains(rect, x, y) {
    return rect && isFinite(x) && isFinite(y)
        && x >= rect.x && y >= rect.y && x < rect.x + rect.w && y < rect.y + rect.h
}

// Every returned rectangle is relative to the usable monitor origin, including
// cards, thumbnails, and miniZones. Painting and hit testing share these exact
// rectangles. The outer card also includes its text label; its thumbnail holds
// the preview surface and miniZones holds the actual proportional zone targets.
function pickerLayout(width, profiles) {
    width = dimension(width)
    var count = Math.min(12, profiles ? profiles.length : 0)
    var empty = {x: 0, y: 0, w: 0, h: 0, columns: 0, rows: 0, cards: []}
    if (!count || width < 180)
        return empty
    var height = dimension(profiles[0].height)
    if (height < 180)
        return empty
    var columns = Math.min(count, Math.max(1, Math.min(6, Math.floor((width - 44) / 164))))
    var rows = Math.ceil(count / columns)
    var cardWidth = Math.min(152, (width - 44 - (columns - 1) * 12) / columns)
    var rowHeight = Math.min(112, (height - 100) / rows)
    if (rowHeight < 48)
        return empty
    var panelWidth = 28 + columns * cardWidth + (columns - 1) * 12
    var picker = {
        x: (width - panelWidth) / 2, y: 18, w: panelWidth, h: 68 + rows * rowHeight,
        padding: 14, headerHeight: 40, cardWidth: cardWidth, cardHeight: rowHeight - 10,
        gap: 12, columns: columns, rows: rows, cards: []
    }
    for (var i = 0; i < count; i++) {
        var profile = profiles[i]
        var card = {
            index: i, x: picker.x + 14 + (i % columns) * (cardWidth + 12),
            y: picker.y + 40 + Math.floor(i / columns) * rowHeight,
            w: cardWidth, h: rowHeight - 10, miniZones: []
        }
        card.thumbnail = {x: card.x, y: card.y, w: card.w, h: card.h - 23}
        var scale = Math.min((card.thumbnail.w - 10) / profile.width, (card.thumbnail.h - 10) / profile.height)
        var originX = card.thumbnail.x + (card.thumbnail.w - profile.width * scale) / 2
        var originY = card.thumbnail.y + (card.thumbnail.h - profile.height * scale) / 2
        for (var z = 0; z < Math.min(64, profile.zones.length); z++) {
            var source = profile.zones[z]
            var w = source.w * scale
            var h = source.h * scale
            var inset = Math.min(1.5, w / 8, h / 8)
            card.miniZones.push({x: originX + source.x * scale + inset, y: originY + source.y * scale + inset,
                w: w - 2 * inset, h: h - 2 * inset, index: z})
        }
        picker.cards.push(card)
    }
    return picker
}

// null means no card. A card label/gutter selects the profile without a zone.
function hitPicker(picker, profiles, x, y) {
    if (!picker || !profiles || !contains(picker, x, y))
        return null
    for (var i = 0; i < picker.cards.length; i++) {
        var card = picker.cards[i]
        if (!contains(card, x, y))
            continue
        for (var z = 0; z < card.miniZones.length; z++) {
            if (contains(card.miniZones[z], x, y))
                return {profile: card.index, zone: card.miniZones[z].index}
        }
        return {profile: card.index, zone: -1}
    }
    return null
}

function hitZone(zones, x, y) {
    for (var i = 0; zones && i < Math.min(64, zones.length); i++) {
        if (contains(zones[i], x, y))
            return i
    }
    return -1
}
