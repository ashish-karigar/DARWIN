import EventKit
import Foundation
import AppKit

struct Request: Decodable {
    let action: String
    let title: String?
    let dueDate: String?
    let calendarId: String?
    let id: String?
    let completed: Bool?
    let notes: String?
    let priority: Int?
    let recurrence: String?
}

struct ReminderDTO: Encodable {
    let id: String
    let title: String
    let notes: String?
    let dueDate: String?
    let completed: Bool
    let list: String
    let calendarId: String
    let priority: Int
    let recurrence: String?
}

@main
struct RemindersBridge {
    static let store = EKEventStore()
    static let encoder = JSONEncoder()
    static let iso = ISO8601DateFormatter()
    static var responsePath: String?

    static func main() async {
        guard CommandLine.arguments.count >= 2,
              let input = CommandLine.arguments[1].data(using: .utf8),
              let request = try? JSONDecoder().decode(Request.self, from: input) else {
            respond(["ok": false, "error": "invalid_request"])
            return
        }
        responsePath = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : nil

        switch request.action {
        case "status":
            respond(["ok": true, "status": authorizationStatus()])
        case "requestAccess":
            do {
                let application = NSApplication.shared
                application.setActivationPolicy(.accessory)
                application.activate(ignoringOtherApps: true)
                let granted = try await store.requestFullAccessToReminders()
                let status = authorizationStatus()
                if !granted && status == "notDetermined" {
                    respond(["ok": false, "error": "permission_prompt_not_presented", "status": status])
                } else {
                    respond(["ok": true, "granted": granted, "status": status])
                }
            } catch {
                respond(["ok": false, "error": "access_request_failed"])
            }
        case "list":
            guard hasAccess() else { respond(["ok": false, "error": "access_denied", "status": authorizationStatus()]); return }
            let reminders = await fetchReminders()
            respondEncodable(["ok": true], reminders: reminders)
        case "create":
            guard hasAccess(), let title = request.title else { respond(["ok": false, "error": "access_denied"]); return }
            let reminder = EKReminder(eventStore: store)
            reminder.title = title
            reminder.calendar = request.calendarId.flatMap { store.calendar(withIdentifier: $0) } ?? store.defaultCalendarForNewReminders()
            if let value = request.dueDate, let date = iso.date(from: value) {
                reminder.dueDateComponents = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
            }
            do { try store.save(reminder, commit: true); respond(["ok": true, "id": reminder.calendarItemIdentifier]) }
            catch { respond(["ok": false, "error": "save_failed"]) }
        case "complete":
            guard hasAccess(), let id = request.id,
                  let reminder = store.calendarItem(withIdentifier: id) as? EKReminder else { respond(["ok": false, "error": "not_found"]); return }
            reminder.isCompleted = request.completed ?? true
            do { try store.save(reminder, commit: true); respond(["ok": true]) }
            catch { respond(["ok": false, "error": "save_failed"]) }
        case "update":
            guard hasAccess(), let id = request.id,
                  let reminder = store.calendarItem(withIdentifier: id) as? EKReminder else { respond(["ok": false, "error": "not_found"]); return }
            if let title = request.title { reminder.title = title }
            if let notes = request.notes { reminder.notes = notes }
            if let priority = request.priority { reminder.priority = priority }
            if let calendarId = request.calendarId, let calendar = store.calendar(withIdentifier: calendarId) { reminder.calendar = calendar }
            if let value = request.dueDate { reminder.dueDateComponents = iso.date(from: value).map { Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: $0) } }
            if let recurrence = request.recurrence {
                let frequency: EKRecurrenceFrequency? = recurrence == "daily" ? .daily : recurrence == "weekly" ? .weekly : recurrence == "monthly" ? .monthly : recurrence == "yearly" ? .yearly : nil
                reminder.recurrenceRules = frequency.map { [EKRecurrenceRule(recurrenceWith: $0, interval: 1, end: nil)] }
            }
            do { try store.save(reminder, commit: true); respond(["ok": true]) }
            catch { respond(["ok": false, "error": "save_failed"]) }
        case "delete":
            guard hasAccess(), let id = request.id,
                  let reminder = store.calendarItem(withIdentifier: id) as? EKReminder else { respond(["ok": false, "error": "not_found"]); return }
            do { try store.remove(reminder, commit: true); respond(["ok": true]) }
            catch { respond(["ok": false, "error": "delete_failed"]) }
        default:
            respond(["ok": false, "error": "invalid_action"])
        }
    }

    static func authorizationStatus() -> String {
        switch EKEventStore.authorizationStatus(for: .reminder) {
        case .notDetermined: return "notDetermined"
        case .restricted: return "restricted"
        case .denied: return "denied"
        case .fullAccess: return "fullAccess"
        case .writeOnly: return "writeOnly"
        @unknown default: return "unknown"
        }
    }

    static func hasAccess() -> Bool { EKEventStore.authorizationStatus(for: .reminder) == .fullAccess }

    static func fetchReminders() async -> [ReminderDTO] {
        let values: [EKReminder] = await withCheckedContinuation { continuation in
            store.fetchReminders(matching: store.predicateForReminders(in: nil)) { continuation.resume(returning: $0 ?? []) }
        }
        return values.map {
            let due = $0.dueDateComponents.flatMap { Calendar.current.date(from: $0) }.map { iso.string(from: $0) }
            let recurrence = $0.recurrenceRules?.first.map { $0.frequency == .daily ? "daily" : $0.frequency == .weekly ? "weekly" : $0.frequency == .monthly ? "monthly" : "yearly" }
            return ReminderDTO(id: $0.calendarItemIdentifier, title: $0.title, notes: $0.notes, dueDate: due, completed: $0.isCompleted, list: $0.calendar.title, calendarId: $0.calendar.calendarIdentifier, priority: $0.priority, recurrence: recurrence)
        }
    }

    static func respond(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value) else { exit(1) }
        writeResponse(data)
    }

    static func respondEncodable(_ metadata: [String: Bool], reminders: [ReminderDTO]) {
        struct Response: Encodable { let ok: Bool; let reminders: [ReminderDTO] }
        guard let data = try? encoder.encode(Response(ok: metadata["ok"] ?? false, reminders: reminders)) else { exit(1) }
        writeResponse(data)
    }

    static func writeResponse(_ data: Data) {
        if let responsePath {
            try? data.write(to: URL(fileURLWithPath: responsePath), options: .atomic)
        } else {
            FileHandle.standardOutput.write(data)
        }
    }
}
