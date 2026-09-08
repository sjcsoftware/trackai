import AppKit

enum StatusIcon {
    /// The menu bar glyph: one provider's own mark when a single provider drives
    /// the icon, otherwise the aggregate bolt.
    static func image(percent: Double?, color: NSColor, glyph: ProviderKind?, size: CGFloat = 18) -> NSImage {
        if let glyph {
            return ProviderMark.image(glyph, size: size, color: color)
        }
        return bolt(percent: percent, color: color, size: size)
    }

    /// The aggregate mark: a lightning bolt that fills from the bottom as usage
    /// climbs. A ring gauge reads as a generic progress circle at menu bar size;
    /// the bolt keeps a distinctive silhouette at 18pt, and the outline stays
    /// visible at low usage so the icon never looks like it has gone missing.
    static func bolt(percent: Double?, color: NSColor, size: CGFloat = 18) -> NSImage {
        let level = CGFloat(min(100, max(0, percent ?? 0)) / 100)
        let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
            let lineWidth = max(1, size * 0.09)
            // Inset by half the stroke so the outline is not clipped at the edges.
            let box = rect.insetBy(dx: lineWidth / 2, dy: lineWidth / 2)
            let path = boltPath(in: box)

            // Ghost body: gives the bolt presence even at 0%.
            color.withAlphaComponent(0.22).setFill()
            path.fill()

            if level > 0 {
                NSGraphicsContext.saveGraphicsState()
                path.addClip()
                color.setFill()
                NSBezierPath(rect: NSRect(x: box.minX, y: box.minY,
                                          width: box.width, height: box.height * level)).fill()
                NSGraphicsContext.restoreGraphicsState()
            }

            path.lineWidth = lineWidth
            path.lineJoinStyle = .round
            color.setStroke()
            path.stroke()
            return true
        }
        image.isTemplate = false
        return image
    }

    /// Lightning bolt in normalised coordinates, scaled into `rect`.
    private static func boltPath(in rect: NSRect) -> NSBezierPath {
        func point(_ x: CGFloat, _ y: CGFloat) -> NSPoint {
            NSPoint(x: rect.minX + x * rect.width, y: rect.minY + y * rect.height)
        }
        let path = NSBezierPath()
        path.move(to: point(0.62, 1.00))
        path.line(to: point(0.18, 0.44))
        path.line(to: point(0.46, 0.44))
        path.line(to: point(0.26, 0.00))
        path.line(to: point(0.82, 0.56))
        path.line(to: point(0.54, 0.56))
        path.close()
        return path
    }
}
