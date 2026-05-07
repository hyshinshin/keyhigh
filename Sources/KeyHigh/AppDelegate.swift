import AppKit
import SwiftUI
import Combine

final class AppDelegate: NSObject, NSApplicationDelegate {

    private var tracker: TypingSpeedTracker?
    private var monitor: TypingMonitor?
    private var store: InstancesStore?

    private var panels: [UUID: CharacterPanel] = [:]
    private var cancellables: Set<AnyCancellable> = []
    private var sizeCancellables: [UUID: AnyCancellable] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Background-style app: no Dock icon, no menu bar item.
        NSApp.setActivationPolicy(.accessory)

        let library = VideoLoader.loadLibrary()
        if library.isEmpty {
            fputs("KeyHigh: no <name>_idle.* / <name>_run.* video pairs found in Resources — placeholder will show.\n", stderr)
        }

        let tracker = TypingSpeedTracker()
        let store = InstancesStore(library: library)
        self.tracker = tracker
        self.store = store

        // Spawn one panel per instance, then keep them in sync as the store mutates.
        for inst in store.instances {
            spawnPanel(for: inst, tracker: tracker, store: store)
        }
        store.$instances
            .sink { [weak self] list in
                self?.syncPanels(with: list, tracker: tracker, store: store)
            }
            .store(in: &cancellables)

        let monitor = TypingMonitor(tracker: tracker)
        monitor.start()
        self.monitor = monitor
    }

    private func syncPanels(with instances: [CharacterInstance],
                            tracker: TypingSpeedTracker,
                            store: InstancesStore) {
        let aliveIDs = Set(instances.map { $0.id })
        // remove panels whose instance is gone
        for id in Array(panels.keys) where !aliveIDs.contains(id) {
            panels[id]?.orderOut(nil)
            panels.removeValue(forKey: id)
            sizeCancellables.removeValue(forKey: id)
        }
        // spawn panels for newly added instances
        for inst in instances where panels[inst.id] == nil {
            spawnPanel(for: inst, tracker: tracker, store: store)
        }
    }

    private func spawnPanel(for instance: CharacterInstance,
                            tracker: TypingSpeedTracker,
                            store: InstancesStore) {
        let frame = NSRect(origin: instance.origin, size: instance.size.nsSize)
        let panel = CharacterPanel(initialFrame: frame)

        let view = CharacterView(tracker: tracker, instance: instance, store: store)
        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: instance.size.nsSize)
        host.autoresizingMask = [.width, .height]
        panel.contentView = host

        panel.onClick = { [weak instance] in
            instance?.recordClick()
        }
        panel.onMove = { [weak instance] newOrigin in
            instance?.updateOrigin(newOrigin)
        }

        panel.orderFrontRegardless()
        panels[instance.id] = panel

        // Resize the panel whenever this instance's size changes.
        sizeCancellables[instance.id] = instance.$sizeRaw
            .removeDuplicates()
            .dropFirst()
            .sink { [weak panel, weak instance] _ in
                guard let panel, let instance else { return }
                panel.applySize(instance.size.nsSize)
            }
    }

    func applicationWillTerminate(_ notification: Notification) {
        monitor?.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}
