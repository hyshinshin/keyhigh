import Foundation
import AppKit

/// One on-screen character: which character pair, what size, where it sits,
/// and a per-instance click boost that adds onto the global typing CPS.
final class CharacterInstance: ObservableObject, Identifiable {

    let id: UUID

    @Published var characterID: String
    @Published var sizeRaw: Int
    @Published private(set) var clickBoost: Double = 0

    /// Not @Published — frequent drag updates would churn SwiftUI; the panel
    /// already drives its own frame and just calls `updateOrigin` for persistence.
    var origin: NSPoint

    let library: [CharacterAssets]
    weak var store: InstancesStore?

    private var boostTimer: Timer?
    private let boostPerClick: Double = 4.0
    private let boostCap: Double      = 10.0
    private let boostDecayPerTick: Double = 0.4   // tick = 0.1s → ~4 cps/sec decay

    init(id: UUID = UUID(),
         characterID: String,
         sizeRaw: Int,
         origin: NSPoint,
         library: [CharacterAssets]) {
        self.id = id
        self.characterID = characterID
        self.sizeRaw = sizeRaw
        self.origin = origin
        self.library = library
    }

    deinit {
        boostTimer?.invalidate()
    }

    var character: CharacterAssets? {
        library.first(where: { $0.id == characterID })
            ?? library.first(where: { $0.id == "mouse" })
            ?? library.first
    }

    var size: CharacterSize {
        CharacterSize(rawValue: sizeRaw) ?? .small
    }

    func setCharacterID(_ newID: String) {
        guard library.contains(where: { $0.id == newID }) else { return }
        characterID = newID
        store?.scheduleSave()
    }

    func setSize(_ s: CharacterSize) {
        sizeRaw = s.rawValue
        store?.scheduleSave()
    }

    func updateOrigin(_ p: NSPoint) {
        origin = p
        store?.scheduleSave()
    }

    func recordClick() {
        clickBoost = min(clickBoost + boostPerClick, boostCap)
        startDecayIfNeeded()
    }

    private func startDecayIfNeeded() {
        guard boostTimer == nil else { return }
        boostTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.clickBoost = max(0, self.clickBoost - self.boostDecayPerTick)
            if self.clickBoost == 0 {
                self.boostTimer?.invalidate()
                self.boostTimer = nil
            }
        }
    }
}
