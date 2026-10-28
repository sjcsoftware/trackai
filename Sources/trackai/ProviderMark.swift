import AppKit
import SwiftUI

/// The providers' official marks, drawn from their published SVG outlines so the
/// app carries no image assets and the glyphs stay crisp at any size and in
/// either appearance.
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
            tint.setFill()
            path(kind, in: rect).fill()
            return true
        }
    }

    /// The mark's outline scaled into `rect`. The SVG sources use a 24×24
    /// y-down viewBox; AppKit is y-up, so the transform flips as it scales.
    static func path(_ kind: ProviderKind, in rect: NSRect) -> NSBezierPath {
        let path = parse(kind == .claude ? claudeOutline : codexOutline)
        let scale = min(rect.width, rect.height) / 24
        var transform = AffineTransform(translationByX: rect.midX - 12 * scale, byY: rect.midY + 12 * scale)
        transform.scale(x: scale, y: -scale)
        path.transform(using: transform)
        path.windingRule = .evenOdd
        return path
    }

    /// Reads the absolute M/L/C/Z subset the outlines below are normalised to.
    private static func parse(_ data: String) -> NSBezierPath {
        let path = NSBezierPath()
        let tokens = data.split(whereSeparator: { $0 == " " || $0 == "\n" })
        var i = 0
        func next() -> CGFloat { defer { i += 1 }; return CGFloat(Double(tokens[i]) ?? 0) }
        func point() -> NSPoint { let x = next(); return NSPoint(x: x, y: next()) }
        while i < tokens.count {
            let op = tokens[i]
            i += 1
            switch op {
            case "M": path.move(to: point())
            case "L": path.line(to: point())
            case "C":
                let c1 = point(), c2 = point()
                path.curve(to: point(), controlPoint1: c1, controlPoint2: c2)
            case "Z": path.close()
            default: break
            }
        }
        return path
    }

    /// Claude's starburst (Anthropic brand mark), viewBox 0 0 24 24.
    private static let claudeOutline = """
        M 4.709 15.955 L 9.429 13.308 L 9.509 13.078 L 9.429 12.95 L 9.2 12.95 L 8.41 12.902
        L 5.712 12.829 L 3.373 12.732 L 1.107 12.61 L 0.536 12.489 L 0 11.784 L 0.055 11.432
        L 0.535 11.111 L 1.221 11.171 L 2.741 11.274 L 5.019 11.432 L 6.671 11.529 L 9.12 11.784
        L 9.509 11.784 L 9.564 11.627 L 9.43 11.529 L 9.327 11.432 L 6.969 9.836 L 4.417 8.148
        L 3.081 7.176 L 2.357 6.685 L 1.993 6.223 L 1.835 5.215 L 2.491 4.493 L 3.372 4.553
        L 3.597 4.614 L 4.49 5.3 L 6.398 6.776 L 8.889 8.609 L 9.254 8.913 L 9.399 8.81
        L 9.418 8.737 L 9.254 8.463 L 7.899 6.017 L 6.453 3.527 L 5.809 2.495 L 5.639 1.876
        C 5.574 1.638 5.539 1.393 5.535 1.147 L 6.283 0.134 L 6.696 0 L 7.692 0.134
        L 8.112 0.498 L 8.732 1.912 L 9.734 4.141 L 11.289 7.171 L 11.745 8.069 L 11.988 8.901
        L 12.079 9.156 L 12.237 9.156 L 12.237 9.01 L 12.365 7.304 L 12.602 5.209 L 12.832 2.514
        L 12.912 1.754 L 13.288 0.844 L 14.035 0.352 L 14.619 0.632 L 15.099 1.317
        L 15.032 1.761 L 14.746 3.612 L 14.187 6.515 L 13.823 8.457 L 14.035 8.457
        L 14.278 8.215 L 15.263 6.909 L 16.915 4.845 L 17.645 4.025 L 18.495 3.121 L 19.042 2.69
        L 20.075 2.69 L 20.835 3.819 L 20.495 4.985 L 19.431 6.332 L 18.55 7.474 L 17.286 9.174
        L 16.496 10.534 L 16.569 10.644 L 16.757 10.624 L 19.613 10.018 L 21.156 9.738
        L 22.997 9.423 L 23.83 9.811 L 23.921 10.206 L 23.593 11.013 L 21.624 11.499
        L 19.315 11.961 L 15.876 12.774 L 15.834 12.804 L 15.883 12.865 L 17.432 13.011
        L 18.094 13.047 L 19.716 13.047 L 22.736 13.272 L 23.526 13.794 L 24 14.432
        L 23.921 14.917 L 22.706 15.537 L 21.066 15.148 L 17.237 14.238 L 15.925 13.909
        L 15.743 13.909 L 15.743 14.019 L 16.836 15.087 L 18.842 16.897 L 21.351 19.227
        L 21.478 19.805 L 21.156 20.26 L 20.816 20.211 L 18.611 18.554 L 17.76 17.807
        L 15.834 16.187 L 15.706 16.187 L 15.706 16.357 L 16.15 17.006 L 18.495 20.527
        L 18.617 21.607 L 18.447 21.96 L 17.839 22.173 L 17.171 22.051 L 15.797 20.126
        L 14.382 17.959 L 13.239 16.016 L 13.099 16.096 L 12.425 23.35 L 12.109 23.72 L 11.38 24
        L 10.773 23.539 L 10.451 22.792 L 10.773 21.316 L 11.162 19.392 L 11.477 17.862
        L 11.763 15.962 L 11.933 15.33 L 11.921 15.288 L 11.781 15.306 L 10.347 17.273
        L 8.167 20.218 L 6.441 22.063 L 6.027 22.227 L 5.31 21.857 L 5.377 21.195 L 5.778 20.606
        L 8.166 17.57 L 9.606 15.688 L 10.536 14.602 L 10.53 14.444 L 10.475 14.444
        L 4.132 18.56 L 3.002 18.706 L 2.515 18.25 L 2.576 17.504 L 2.807 17.261 L 4.715 15.949
        L 4.709 15.955 Z
        """

    /// The Codex mark (cloud with a `>_` prompt cut out), viewBox 0 0 24 24.
    private static let codexOutline = """
        M 8.086 0.457 C 9.049 0.061 10.098 -0.082 11.132 0.042
        C 12.465 0.195 13.653 0.762 14.696 1.742 C 14.725 1.769 14.765 1.78 14.803 1.771
        C 16.211 1.425 17.565 1.547 18.864 2.137 L 18.927 2.167 L 19.081 2.243
        C 20.438 2.946 21.411 4.013 21.999 5.441 C 22.277 6.12 22.417 6.829 22.42 7.567
        C 22.44 8.117 22.379 8.666 22.24 9.198 C 22.226 9.253 22.241 9.312 22.28 9.353
        C 23.066 10.15 23.613 11.152 23.858 12.244 C 24.243 14.145 23.848 15.859 22.675 17.384
        L 22.493 17.604 C 21.716 18.494 20.696 19.137 19.559 19.455
        C 19.509 19.47 19.468 19.508 19.451 19.557 C 19.196 20.293 18.94 20.921 18.464 21.549
        C 17.265 23.131 15.502 24.011 13.516 24 C 11.933 23.992 10.53 23.413 9.306 22.264
        C 9.268 22.229 9.215 22.217 9.166 22.232 C 8.648 22.399 8.126 22.423 7.562 22.417
        C 6.661 22.41 5.773 22.197 4.967 21.795 C 4.123 21.376 3.388 20.766 2.821 20.014
        C 2.618 19.745 2.417 19.492 2.27 19.193 C 2.067 18.781 1.902 18.352 1.775 17.91
        C 1.509 16.907 1.503 15.852 1.758 14.846 C 1.766 14.822 1.769 14.797 1.766 14.772
        C 1.761 14.747 1.748 14.725 1.729 14.708 C 1.113 14.084 0.641 13.333 0.349 12.506
        C 0.155 11.997 0.043 11.461 0.016 10.917 C -0.032 10.201 0.031 9.482 0.204 8.785
        C 0.654 7.301 1.513 6.137 2.781 5.292 C 3.063 5.104 3.331 4.958 3.583 4.854
        C 3.869 4.734 4.156 4.634 4.444 4.55 C 4.486 4.538 4.519 4.505 4.531 4.463
        C 4.749 3.678 5.125 2.945 5.635 2.31 C 6.315 1.464 7.132 0.846 8.086 0.457 Z
        M 7.282 8.307 C 7.049 7.9 6.531 7.759 6.125 7.992 C 5.718 8.224 5.576 8.742 5.809 9.149
        L 7.503 12.114 L 5.815 14.962 C 5.6 15.363 5.739 15.862 6.131 16.094
        C 6.522 16.326 7.027 16.207 7.275 15.826 L 9.215 12.554
        C 9.371 12.291 9.373 11.965 9.222 11.7 L 7.282 8.307 Z M 12.728 14.547
        C 12.279 14.574 11.929 14.945 11.929 15.395 C 11.929 15.844 12.279 16.215 12.728 16.242
        L 17.576 16.242 C 18.028 16.22 18.384 15.847 18.384 15.394
        C 18.384 14.941 18.028 14.568 17.576 14.546 L 12.728 14.546 Z
        """
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
