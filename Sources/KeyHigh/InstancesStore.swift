import Foundation
import AppKit

private struct PersistedInstance: Codable {
    var id: UUID
    var characterID: String
    var sizeRaw: Int
    var originX: Double
    var originY: Double
}

/// Owns the live array of `CharacterInstance` objects and persists them to
/// UserDefaults as a single JSON blob. Adds/removes here drive the panel
/// fan-out in AppDelegate.
final class InstancesStore: ObservableObject {

    static let maxInstances = 5
    private static let defaultsKey = "instances"

    @Published private(set) var instances: [CharacterInstance]

    private let library: [CharacterAssets]
    private var saveScheduled = false

    init(library: [CharacterAssets]) {
        self.library = library

        let loaded = Self.load(library: library)
        if loaded.isEmpty {
            // First run: seed with one mouse-character at the default origin.
            let size = CharacterSize.small
            let inst = CharacterInstance(
                characterID: "mouse",
                sizeRaw: size.rawValue,
                origin: Self.defaultOrigin(forSize: size.nsSize, indexOffset: 0),
                library: library
            )
            self.instances = [inst]
        } else {
            self.instances = loaded
        }
        self.instances.forEach { $0.store = self }
    }

    @discardableResult
    func add() -> CharacterInstance? {
        guard instances.count < Self.maxInstances else { return nil }
        let size = CharacterSize.small
        let origin = Self.defaultOrigin(forSize: size.nsSize, indexOffset: instances.count)
        let inst = CharacterInstance(
            characterID: "mouse",
            sizeRaw: size.rawValue,
            origin: origin,
            library: library
        )
        inst.store = self
        instances.append(inst)
        scheduleSave()
        return inst
    }

    func remove(_ instance: CharacterInstance) {
        guard instances.count > 1 else { return }   // keep at least one on screen
        instances.removeAll { $0.id == instance.id }
        scheduleSave()
    }

    /// Coalesce rapid mutations (drag, repeated clicks) into a single
    /// UserDefaults write per main-runloop tick.
    func scheduleSave() {
        guard !saveScheduled else { return }
        saveScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.saveScheduled = false
            self.persist()
        }
    }

    private func persist() {
        let payload = instances.map {
            PersistedInstance(
                id: $0.id,
                characterID: $0.characterID,
                sizeRaw: $0.sizeRaw,
                originX: Double($0.origin.x),
                originY: Double($0.origin.y)
            )
        }
        if let data = try? JSONEncoder().encode(payload) {
            UserDefaults.standard.set(data, forKey: Self.defaultsKey)
        }
    }

    private static func load(library: [CharacterAssets]) -> [CharacterInstance] {
        guard let data = UserDefaults.standard.data(forKey: defaultsKey),
              let payload = try? JSONDecoder().decode([PersistedInstance].self, from: data),
              !payload.isEmpty
        else { return [] }
        return payload.map { p in
            CharacterInstance(
                id: p.id,
                characterID: p.characterID,
                sizeRaw: p.sizeRaw,
                origin: NSPoint(x: p.originX, y: p.originY),
                library: library
            )
        }
    }

    static func defaultOrigin(forSize size: NSSize, indexOffset: Int) -> NSPoint {
        guard let screen = NSScreen.main else { return .zero }
        let visible = screen.visibleFrame
        let margin: CGFloat = 24
        let stagger: CGFloat = CGFloat(indexOffset) * (size.width + 16)
        return NSPoint(
            x: visible.maxX - size.width - margin - stagger,
            y: visible.minY + margin
        )
    }
}
