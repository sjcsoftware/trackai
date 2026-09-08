import AppKit
import SwiftUI

/// Small vector marks drawn for each provider, so the app carries no image
/// assets and the glyphs stay crisp at any size and in either appearance.
enum ProviderMark {
    static let claudeOrange = NSColor(calibratedRed: 0.851, green: 0.467, blue: 0.341, alpha: 1)

    static func brandColor(_ kind: ProviderKind) -> NSColor {
        switch kind {
        case .claude: return claudeOrange
        case .codex: return NSColor.labelColor
        }
    }

    static func image(_ kind: ProviderKind, size: CGFloat, color: NSColor? = nil) -> NSImage {
        let tint = color ?? brandColor(kind)
        return NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
            switch kind {
            case .claude: drawStarburst(in: rect, color: tint)
            case .codex: drawKnot(in: rect, color: tint)
            }
            return true
        }
    }

    /// Claude's ten-ray starburst; slightly irregular ray lengths give it the
    /// organic feel of the real mark rather than a mechanical asterisk.
    static func drawStarburst(in rect: NSRect, color: NSColor) {
        let size = min(rect.width, rect.height)
        let center = NSPoint(x: rect.midX, y: rect.midY)
        let lengths: [CGFloat] = [1.0, 0.78, 0.95, 0.8, 1.0, 0.78, 0.95, 0.8, 1.0, 0.78]
        let outerMax = size * 0.46
        let inner = size * 0.12

        color.setStroke()
        for i in 0..<10 {
            let angle = (CGFloat(i) / 10) * 2 * .pi + .pi / 2
            let outer = outerMax * lengths[i]
            let path = NSBezierPath()
            path.lineWidth = max(1, size * 0.13)
            path.lineCapStyle = .round
            path.move(to: NSPoint(x: center.x + cos(angle) * inner, y: center.y + sin(angle) * inner))
            path.line(to: NSPoint(x: center.x + cos(angle) * outer, y: center.y + sin(angle) * outer))
            path.stroke()
        }
    }

    /// A hexagonal knot standing in for the OpenAI mark: the outer ring plus the
    /// three interior spokes that give the logo its woven look.
    static func drawKnot(in rect: NSRect, color: NSColor) {
        let size = min(rect.width, rect.height)
        let center = NSPoint(x: rect.midX, y: rect.midY)
        let radius = size * 0.42
        let line = max(1, size * 0.11)

        func vertex(_ i: Int) -> NSPoint {
            let angle = (CGFloat(i) / 6) * 2 * .pi + .pi / 6
            return NSPoint(x: center.x + cos(angle) * radius, y: center.y + sin(angle) * radius)
        }

        color.setStroke()
        let ring = NSBezierPath()
        ring.lineWidth = line
        ring.lineJoinStyle = .round
        ring.lineCapStyle = .round
        ring.move(to: vertex(0))
        for i in 1..<6 { ring.line(to: vertex(i)) }
        ring.close()
        ring.stroke()

        let spokes = NSBezierPath()
        spokes.lineWidth = line
        spokes.lineCapStyle = .round
        for i in stride(from: 0, to: 6, by: 2) {
            spokes.move(to: center)
            spokes.line(to: vertex(i))
        }
        spokes.stroke()
    }
}

/// SwiftUI wrapper so provider boxes can drop the mark straight into a stack.
struct ProviderMarkView: View {
    let kind: ProviderKind
    var size: CGFloat = 16
    var color: NSColor?

    var body: some View {
        Image(nsImage: ProviderMark.image(kind, size: size, color: color))
            .frame(width: size, height: size)
    }
}
