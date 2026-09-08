import AppKit

enum StatusIcon {
    /// The menu bar glyph: a ring gauge filled to the reported percentage, or a
    /// provider mark when a single provider drives the icon.
    static func image(percent: Double?, color: NSColor, glyph: ProviderKind?, size: CGFloat = 18) -> NSImage {
        if let glyph {
            return ProviderMark.image(glyph, size: size, color: color)
        }
        return gauge(percent: percent, color: color, size: size)
    }

    static func gauge(percent: Double?, color: NSColor, size: CGFloat = 18) -> NSImage {
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
            let center = NSPoint(x: rect.midX, y: rect.midY)
            let radius = size * 0.36
            let line = max(1.5, size * 0.15)

            let track = NSBezierPath()
            track.appendArc(withCenter: center, radius: radius, startAngle: 0, endAngle: 360)
            track.lineWidth = line
            color.withAlphaComponent(0.22).setStroke()
            track.stroke()

            if let percent, percent > 0 {
                let sweep = min(360, max(6, 360 * percent / 100))
                let arc = NSBezierPath()
                // Start at 12 o'clock and sweep clockwise, like a dial filling up.
                arc.appendArc(withCenter: center, radius: radius,
                              startAngle: 90, endAngle: 90 - sweep, clockwise: true)
                arc.lineWidth = line
                arc.lineCapStyle = .round
                color.setStroke()
                arc.stroke()
            }
            return true
        }
        image.isTemplate = false
        return image
    }
}
