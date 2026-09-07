import CoreGraphics
import Foundation

let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
guard let info = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else {
    FileHandle.standardOutput.write(Data("[]\n".utf8))
    exit(0)
}

var rows: [[String: Any]] = []
for w in info {
    let bounds = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    rows.append([
        "id": w[kCGWindowNumber as String] as? Int ?? -1,
        "pid": w[kCGWindowOwnerPID as String] as? Int ?? -1,
        "name": w[kCGWindowName as String] as? String ?? "",
        "owner": w[kCGWindowOwnerName as String] as? String ?? "",
        "layer": w[kCGWindowLayer as String] as? Int ?? 0,
        "x": bounds["X"] as? Double ?? 0,
        "y": bounds["Y"] as? Double ?? 0,
        "w": bounds["Width"] as? Double ?? 0,
        "h": bounds["Height"] as? Double ?? 0,
    ])
}

let data = try JSONSerialization.data(withJSONObject: rows)
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data("\n".utf8))
