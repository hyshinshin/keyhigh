import SwiftUI

struct CharacterView: View {

    @ObservedObject var tracker: TypingSpeedTracker
    @ObservedObject var instance: CharacterInstance
    @ObservedObject var store: InstancesStore

    private var isAnimating: Bool {
        tracker.state == .running || instance.clickBoost > 0
    }

    private var currentURL: URL? {
        guard let character = instance.character else { return nil }
        return isAnimating ? character.runURL : character.idleURL
    }

    /// Maps typing speed (+ per-instance click boost) to playback rate.
    /// Idle is fixed at 0.7×. Running scales with effective CPS, capped at 4×
    /// (raised from 3× so click bursts can push past pure-typing top speed).
    private var currentRate: Double {
        let effectiveCPS = tracker.cps + instance.clickBoost
        if !isAnimating { return 0.7 }
        let scaled = 0.8 + effectiveCPS * 0.25
        return min(max(scaled, 0.8), 4.0)
    }

    private var sideLength: CGFloat {
        CGFloat(instance.size.rawValue)
    }

    var body: some View {
        ZStack {
            if let currentURL {
                ChromaKeyVideoView(videoURL: currentURL, rate: currentRate)
            } else {
                placeholder
            }
        }
        .frame(width: sideLength, height: sideLength)
        .contentShape(Rectangle())
        .contextMenu { menu }
    }

    @ViewBuilder
    private var menu: some View {
        if !instance.library.isEmpty {
            Section("Character") {
                ForEach(instance.library) { character in
                    Button {
                        instance.setCharacterID(character.id)
                    } label: {
                        if character.id == instance.characterID {
                            Label(character.displayName, systemImage: "checkmark")
                        } else {
                            Text(character.displayName)
                        }
                    }
                }
            }
        }
        Section("Size") {
            ForEach(CharacterSize.allCases) { size in
                Button {
                    instance.setSize(size)
                } label: {
                    if size.rawValue == instance.sizeRaw {
                        Label(size.displayName, systemImage: "checkmark")
                    } else {
                        Text(size.displayName)
                    }
                }
            }
        }
        Divider()
        Button("Add Character (\(store.instances.count)/\(InstancesStore.maxInstances))") {
            _ = store.add()
        }
        .disabled(store.instances.count >= InstancesStore.maxInstances)
        Button("Remove This Character") {
            store.remove(instance)
        }
        .disabled(store.instances.count <= 1)
        Divider()
        Button("Quit KeyHigh") {
            NSApp.terminate(nil)
        }
    }

    private var placeholder: some View {
        VStack(spacing: 4) {
            Text("KeyHigh")
                .font(.system(size: 14, weight: .semibold))
            Text("drop <name>_idle.mov\nand <name>_run.mov\ninto Resources/")
                .font(.system(size: 10))
                .multilineTextAlignment(.center)
                .opacity(0.85)
        }
        .padding(10)
        .foregroundStyle(.white)
        .background(.black.opacity(0.55), in: RoundedRectangle(cornerRadius: 12))
    }
}
