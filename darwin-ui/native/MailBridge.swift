import AppKit
import Foundation

struct MailRequest: Decodable {
    let action: String
    let sender: String?
    let mailbox: String?
    let maxMessages: Int?
}

struct MailMessageDTO: Encodable {
    let id: String
    let sender: String
    let subject: String
    let receivedAt: String
    let account: String
    let mailbox: String
    let body: String
}

@main
struct MailBridge {
    static var responsePath: String?

    static func main() {
        guard CommandLine.arguments.count >= 2,
              let data = CommandLine.arguments[1].data(using: .utf8),
              let request = try? JSONDecoder().decode(MailRequest.self, from: data) else {
            respond(["ok": false, "error": "invalid_request"])
            return
        }
        responsePath = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : nil
        NSApplication.shared.setActivationPolicy(.accessory)

        switch request.action {
        case "requestAccess":
            runAccessProbe()
        case "scan":
            scan(request)
        default:
            respond(["ok": false, "error": "invalid_action"])
        }
    }

    static func runAccessProbe() {
        var error: NSDictionary?
        let result = NSAppleScript(source: "tell application \"Mail\" to get name")?
            .executeAndReturnError(&error)
        if result != nil { respond(["ok": true, "status": "authorized"]); return }
        respond(["ok": false, "status": "denied", "error": automationError(error)])
    }

    static func scan(_ request: MailRequest) {
        guard let sender = request.sender?.trimmingCharacters(in: .whitespacesAndNewlines),
              !sender.isEmpty else {
            respond(["ok": false, "error": "sender_required"])
            return
        }
        let mailbox = request.mailbox?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
            ? request.mailbox!.trimmingCharacters(in: .whitespacesAndNewlines)
            : "INBOX"
        let maximum = min(25, max(1, request.maxMessages ?? 10))
        let source = """
        set targetSender to \(literal(sender))
        set targetMailboxName to \(literal(mailbox))
        set maximumMessages to \(maximum)
        set resultRows to {}
        tell application "Mail"
          repeat with mailAccount in every account
            set accountName to name of mailAccount as text
            set matchingMailboxes to every mailbox of mailAccount whose name is targetMailboxName
            repeat with targetMailbox in matchingMailboxes
              set matchingMessages to every message of targetMailbox whose sender contains targetSender
              set availableCount to count matchingMessages
              if availableCount > maximumMessages then set availableCount to maximumMessages
              repeat with messageIndex from 1 to availableCount
                set currentMessage to item messageIndex of matchingMessages
                set end of resultRows to {message id of currentMessage as text, sender of currentMessage as text, subject of currentMessage as text, date received of currentMessage as text, accountName, targetMailboxName, content of currentMessage as text}
              end repeat
            end repeat
          end repeat
        end tell
        return resultRows
        """
        var error: NSDictionary?
        guard let descriptor = NSAppleScript(source: source)?.executeAndReturnError(&error) else {
            respond(["ok": false, "error": automationError(error)])
            return
        }
        var messages: [MailMessageDTO] = []
        if descriptor.numberOfItems > 0 {
            for index in 1...descriptor.numberOfItems {
                guard let row = descriptor.atIndex(index), row.numberOfItems >= 7 else { continue }
                let id = row.atIndex(1)?.stringValue ?? ""
                let senderValue = row.atIndex(2)?.stringValue ?? ""
                let subject = row.atIndex(3)?.stringValue ?? "Untitled"
                let receivedAt = row.atIndex(4)?.stringValue ?? ""
                let account = row.atIndex(5)?.stringValue ?? "Mail"
                let mailboxValue = row.atIndex(6)?.stringValue ?? mailbox
                let body = String((row.atIndex(7)?.stringValue ?? "").prefix(50_000))
                guard !id.isEmpty else { continue }
                messages.append(MailMessageDTO(id: id, sender: senderValue, subject: subject, receivedAt: receivedAt, account: account, mailbox: mailboxValue, body: body))
            }
        }
        respondMessages(messages)
    }

    static func literal(_ value: String) -> String {
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
        return "\"\(escaped)\""
    }

    static func automationError(_ details: NSDictionary?) -> String {
        let number = details?[NSAppleScript.errorNumber] as? Int
        return number == -1743 ? "automation_permission_denied" : "mail_unavailable"
    }

    static func respond(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value) else { exit(1) }
        write(data)
    }

    static func respondMessages(_ messages: [MailMessageDTO]) {
        struct Response: Encodable { let ok = true; let messages: [MailMessageDTO] }
        guard let data = try? JSONEncoder().encode(Response(messages: messages)) else { exit(1) }
        write(data)
    }

    static func write(_ data: Data) {
        if let path = responsePath {
            try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
        } else {
            FileHandle.standardOutput.write(data)
        }
    }
}
