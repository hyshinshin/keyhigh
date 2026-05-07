import Foundation
import AppKit

enum CharacterSize: Int, CaseIterable, Identifiable {
    case tiny   = 100
    case small  = 200
    case medium = 400
    case large  = 600

    var id: Int { rawValue }
    var nsSize: NSSize { NSSize(width: rawValue, height: rawValue) }

    var displayName: String {
        switch self {
        case .tiny:   return "Tiny (100)"
        case .small:  return "Small (200)"
        case .medium: return "Medium (400)"
        case .large:  return "Large (600)"
        }
    }
}
