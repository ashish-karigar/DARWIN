import EventKit
import Foundation
import AppKit

struct CalendarRequest: Decodable {
    let action: String
    let id: String?
    let calendarId: String?
    let title: String?
    let notes: String?
    let location: String?
    let startDate: String?
    let endDate: String?
    let rangeStart: String?
    let rangeEnd: String?
    let allDay: Bool?
}

struct CalendarDTO: Encodable {
    let id: String
    let title: String
    let color: String
    let source: String
    let allowsChanges: Bool
}

struct EventDTO: Encodable {
    let id: String
    let calendarId: String
    let calendar: String
    let color: String
    let source: String
    let title: String
    let notes: String?
    let location: String?
    let startDate: String
    let endDate: String
    let allDay: Bool
}

@main
struct CalendarBridge {
    static let store = EKEventStore()
    static let iso: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    static let isoWithoutFractions = ISO8601DateFormatter()
    static var responsePath: String?

    static func main() async {
        guard CommandLine.arguments.count >= 2,
              let data = CommandLine.arguments[1].data(using: .utf8),
              let request = try? JSONDecoder().decode(CalendarRequest.self, from: data) else {
            respond(["ok": false, "error": "invalid_request"]); return
        }
        responsePath = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : nil
        switch request.action {
        case "status": respond(["ok": true, "status": authorizationStatus()])
        case "requestAccess":
            do {
                NSApplication.shared.setActivationPolicy(.accessory)
                NSApplication.shared.activate(ignoringOtherApps: true)
                let granted = try await store.requestFullAccessToEvents()
                respond(["ok": true, "granted": granted, "status": authorizationStatus()])
            } catch { respond(["ok": false, "error": "access_request_failed"]) }
        case "list": list(request)
        case "create": create(request)
        case "update": update(request)
        case "delete": delete(request)
        default: respond(["ok": false, "error": "invalid_action"])
        }
    }

    static func authorizationStatus() -> String {
        switch EKEventStore.authorizationStatus(for: .event) {
        case .notDetermined: return "notDetermined"
        case .restricted: return "restricted"
        case .denied: return "denied"
        case .fullAccess: return "fullAccess"
        case .writeOnly: return "writeOnly"
        @unknown default: return "unknown"
        }
    }

    static func list(_ request: CalendarRequest) {
        guard authorizationStatus() == "fullAccess",
              let startText = request.rangeStart, let endText = request.rangeEnd,
              let start = parseDate(startText), let end = parseDate(endText) else {
            respond(["ok": false, "error": authorizationStatus() == "fullAccess" ? "invalid_range" : "access_denied"]); return
        }
        let calendars = store.calendars(for: .event)
        let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
        let calendarDTOs = calendars.map { CalendarDTO(id: $0.calendarIdentifier, title: $0.title, color: hex($0.cgColor), source: $0.source.title, allowsChanges: $0.allowsContentModifications) }
        let eventDTOs = events.map { event in EventDTO(id: event.eventIdentifier, calendarId: event.calendar.calendarIdentifier, calendar: event.calendar.title, color: hex(event.calendar.cgColor), source: event.calendar.source.title, title: event.title ?? "Untitled", notes: event.notes, location: event.location, startDate: iso.string(from: event.startDate), endDate: iso.string(from: event.endDate), allDay: event.isAllDay) }
        respondEncodable(calendarDTOs, eventDTOs)
    }

    static func create(_ request: CalendarRequest) {
        guard authorizationStatus() == "fullAccess", let title = request.title,
              let startText = request.startDate, let endText = request.endDate,
              let start = parseDate(startText), let end = parseDate(endText) else {
            respond(["ok": false, "error": "invalid_event"]); return
        }
        let event = EKEvent(eventStore: store)
        event.title = title; event.startDate = start; event.endDate = end
        event.notes = request.notes; event.location = request.location; event.isAllDay = request.allDay ?? false
        event.calendar = request.calendarId.flatMap { store.calendar(withIdentifier: $0) } ?? store.defaultCalendarForNewEvents
        save(event)
    }

    static func update(_ request: CalendarRequest) {
        guard authorizationStatus() == "fullAccess", let id = request.id,
              let event = store.event(withIdentifier: id) else { respond(["ok": false, "error": "not_found"]); return }
        if let title = request.title { event.title = title }
        if let value = request.startDate, let date = parseDate(value) { event.startDate = date }
        if let value = request.endDate, let date = parseDate(value) { event.endDate = date }
        if let value = request.notes { event.notes = value }
        if let value = request.location { event.location = value }
        if let value = request.allDay { event.isAllDay = value }
        if let id = request.calendarId, let calendar = store.calendar(withIdentifier: id) { event.calendar = calendar }
        save(event)
    }

    static func delete(_ request: CalendarRequest) {
        guard authorizationStatus() == "fullAccess", let id = request.id,
              let event = store.event(withIdentifier: id) else { respond(["ok": false, "error": "not_found"]); return }
        do { try store.remove(event, span: .thisEvent, commit: true); respond(["ok": true]) }
        catch { respond(["ok": false, "error": "delete_failed"]) }
    }

    static func save(_ event: EKEvent) {
        do { try store.save(event, span: .thisEvent, commit: true); respond(["ok": true, "id": event.eventIdentifier ?? ""]) }
        catch { respond(["ok": false, "error": "save_failed"]) }
    }

    static func parseDate(_ value: String) -> Date? {
        iso.date(from: value) ?? isoWithoutFractions.date(from: value)
    }

    static func hex(_ color: CGColor) -> String {
        guard let values = color.components else { return "#b9965b" }
        let r = Int((values.count > 0 ? values[0] : 0.72) * 255)
        let g = Int((values.count > 1 ? values[1] : 0.59) * 255)
        let b = Int((values.count > 2 ? values[2] : 0.36) * 255)
        return String(format: "#%02X%02X%02X", r, g, b)
    }

    static func respond(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value) else { exit(1) }
        write(data)
    }

    static func respondEncodable(_ calendars: [CalendarDTO], _ events: [EventDTO]) {
        struct Response: Encodable { let ok = true; let calendars: [CalendarDTO]; let events: [EventDTO] }
        guard let data = try? JSONEncoder().encode(Response(calendars: calendars, events: events)) else { exit(1) }
        write(data)
    }

    static func write(_ data: Data) {
        if let path = responsePath { try? data.write(to: URL(fileURLWithPath: path), options: .atomic) }
        else { FileHandle.standardOutput.write(data) }
    }
}
