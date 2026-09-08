// Renders the trackai app icon (a usage dial) as an .iconset.
// Usage: swift scripts/gen-icon.swift <output.iconset>
import AppKit

let args = CommandLine.arguments
guard args.count == 2 else {
    FileHandle.standardError.write("usage: gen-icon.swift <output.iconset>\n".data(using: .utf8)!)
    exit(1)
}
let outDir = URL(fileURLWithPath: args[1])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

func render(size: CGFloat) -> NSImage {
    NSImage(size: NSSize(width: size, height: size), flipped: false) { rect in
        // Rounded-rect dark ground, matching the menu bar app's dark chrome.
        let inset = size * 0.05
        let bg = NSBezierPath(roundedRect: rect.insetBy(dx: inset, dy: inset),
                              xRadius: size * 0.22, yRadius: size * 0.22)
        NSColor(calibratedRed: 0.106, green: 0.102, blue: 0.098, alpha: 1).setFill()
        bg.fill()

        // The dial: green through orange to red, swept clockwise from 12 o'clock.
        let center = NSPoint(x: rect.midX, y: rect.midY)
        let radius = size * 0.28
        let width = size * 0.115
        let steps = 120
        let start: CGFloat = 130
        let sweep: CGFloat = 320

        for i in 0..<steps {
            let t = CGFloat(i) / CGFloat(steps - 1)
            let color: NSColor
            if t < 0.5 {
                color = blend(NSColor(calibratedRed: 0.30, green: 0.78, blue: 0.44, alpha: 1),
                              NSColor(calibratedRed: 0.95, green: 0.62, blue: 0.22, alpha: 1), t / 0.5)
            } else {
                color = blend(NSColor(calibratedRed: 0.95, green: 0.62, blue: 0.22, alpha: 1),
                              NSColor(calibratedRed: 0.90, green: 0.30, blue: 0.28, alpha: 1), (t - 0.5) / 0.5)
            }
            let a0 = start - sweep * t
            let a1 = start - sweep * (t + 1.0 / CGFloat(steps - 1))
            let seg = NSBezierPath()
            seg.appendArc(withCenter: center, radius: radius, startAngle: a0, endAngle: a1, clockwise: true)
            seg.lineWidth = width
            color.setStroke()
            seg.stroke()
        }

        // Claude-orange starburst in the middle: this is a Claude-family tool.
        let lengths: [CGFloat] = [1.0, 0.78, 0.95, 0.8, 1.0, 0.78, 0.95, 0.8, 1.0, 0.78]
        let outerMax = size * 0.155
        let inner = size * 0.04
        NSColor(calibratedRed: 0.851, green: 0.467, blue: 0.341, alpha: 1).setStroke()
        for i in 0..<10 {
            let angle = (CGFloat(i) / 10) * 2 * .pi + .pi / 2
            let path = NSBezierPath()
            path.lineWidth = size * 0.042
            path.lineCapStyle = .round
            path.move(to: NSPoint(x: center.x + cos(angle) * inner, y: center.y + sin(angle) * inner))
            path.line(to: NSPoint(x: center.x + cos(angle) * outerMax * lengths[i],
                                  y: center.y + sin(angle) * outerMax * lengths[i]))
            path.stroke()
        }
        return true
    }
}

func blend(_ a: NSColor, _ b: NSColor, _ t: CGFloat) -> NSColor {
    NSColor(calibratedRed: a.redComponent + (b.redComponent - a.redComponent) * t,
            green: a.greenComponent + (b.greenComponent - a.greenComponent) * t,
            blue: a.blueComponent + (b.blueComponent - a.blueComponent) * t,
            alpha: 1)
}

func writePNG(_ image: NSImage, pixels: Int, name: String) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    image.draw(in: NSRect(x: 0, y: 0, width: pixels, height: pixels))
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: outDir.appendingPathComponent(name))
}

for base in [16, 32, 128, 256, 512] {
    let img = render(size: CGFloat(base))
    writePNG(img, pixels: base, name: "icon_\(base)x\(base).png")
    writePNG(img, pixels: base * 2, name: "icon_\(base)x\(base)@2x.png")
}
print("iconset written to \(outDir.path)")
