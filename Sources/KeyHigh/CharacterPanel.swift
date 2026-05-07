import AppKit

final class CharacterPanel: NSPanel {

    /// Fired when the user clicks the panel without dragging it.
    var onClick: (() -> Void)?

    /// Fired with the new bottom-left origin after a drag gesture finishes.
    var onMove: ((NSPoint) -> Void)?

    init(initialFrame: NSRect) {
        super.init(
            contentRect: initialFrame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isMovable = true
        // We drive drag manually inside mouseDown so we can also detect taps.
        isMovableByWindowBackground = false
        ignoresMouseEvents = false
        isReleasedWhenClosed = false
        hidesOnDeactivate = false
        level = .statusBar
        collectionBehavior = [
            .canJoinAllSpaces,
            .stationary,
            .ignoresCycle,
            .fullScreenAuxiliary
        ]
        animationBehavior = .none
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    override func mouseDown(with event: NSEvent) {
        let startMouse = NSEvent.mouseLocation
        let startOrigin = frame.origin
        var dragged = false
        let dragThreshold: CGFloat = 4

        // Pump events ourselves until the mouse is released; if total motion
        // stays under the threshold treat it as a tap, otherwise drive a drag.
        eventLoop: while let next = nextEvent(matching: [.leftMouseUp, .leftMouseDragged]) {
            switch next.type {
            case .leftMouseUp:
                break eventLoop
            case .leftMouseDragged:
                let cur = NSEvent.mouseLocation
                let dx = cur.x - startMouse.x
                let dy = cur.y - startMouse.y
                if hypot(dx, dy) > dragThreshold { dragged = true }
                if dragged {
                    setFrameOrigin(NSPoint(x: startOrigin.x + dx, y: startOrigin.y + dy))
                }
            default:
                break
            }
        }

        if dragged {
            onMove?(frame.origin)
        } else {
            onClick?()
        }
    }

    func applySize(_ newSize: NSSize) {
        let candidate = NSRect(origin: frame.origin, size: newSize)
        let clamped = Self.clamp(frame: candidate)
        setFrame(clamped, display: true, animate: false)
    }

    private static func clamp(frame: NSRect) -> NSRect {
        let screens = NSScreen.screens
        if screens.contains(where: { $0.visibleFrame.intersects(frame) }) {
            return frame
        }
        if let screen = NSScreen.main {
            let v = screen.visibleFrame
            return NSRect(
                origin: NSPoint(x: v.maxX - frame.width - 24, y: v.minY + 24),
                size: frame.size
            )
        }
        return frame
    }
}
