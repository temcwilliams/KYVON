import KYVONKit

#if canImport(SwiftUI)
import SwiftUI

// MARK: Tasks

struct TasksView: View {
    @ObservedObject var model: AppModel
    @State private var newTitle = ""

    private var overdue: [KTask] { model.openTasks.filter(\.overdue) }
    private var upcoming: [KTask] { model.openTasks.filter { !$0.overdue } }

    var body: some View {
        NavStack {
            List {
                Section {
                    HStack {
                        TextField("Add a task", text: $newTitle).onSubmit(add).submitLabel(.done)
                        Button(action: add) { Image(systemName: "plus.circle.fill") }
                            .disabled(newTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                            .accessibilityLabel("Add task")
                    }
                }
                if model.openTasks.isEmpty && model.doneTasks.isEmpty {
                    EmptyState(symbol: "checklist", title: "Nothing to do",
                               message: "Add a task above, or ask KYVON to add one for you.")
                        .listRowBackground(Color.clear)
                }
                taskSection("Overdue", overdue, tint: Theme.danger)
                taskSection("To do", upcoming, tint: Theme.accent)
                taskSection("Done", Array(model.doneTasks.prefix(10)), tint: Theme.success)
            }
            .navigationTitle("Tasks")
            .refreshable { await model.refreshTasks() }
            .background(Theme.background)
        }
    }

    @ViewBuilder private func taskSection(_ title: String, _ tasks: [KTask], tint: Color) -> some View {
        if !tasks.isEmpty {
            Section(title) {
                ForEach(tasks) { task in
                    TaskRow(task: task, tint: tint) { Task { await model.toggle(task) } }
                        .swipeActions {
                            Button("Delete", role: .destructive) { Task { await model.delete(task) } }
                        }
                }
            }
        }
    }

    private func add() {
        let title = newTitle
        newTitle = ""
        Task { await model.addTask(title) }
    }
}

struct TaskRow: View {
    let task: KTask
    let tint: Color
    let toggle: () -> Void

    private var done: Bool { task.status == "done" }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Button(action: toggle) {
                Image(systemName: done ? "checkmark.circle.fill" : "circle").font(.title3).foregroundStyle(tint)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(done ? "Reopen task" : "Complete task")
            VStack(alignment: .leading, spacing: 2) {
                Text(task.title).strikethrough(done).foregroundStyle(done ? .secondary : .primary)
                Text(detail).font(.caption).foregroundStyle(task.overdue ? Theme.danger : .secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var detail: String {
        var parts: [String] = []
        if task.overdue { parts.append("Overdue") }
        if let due = task.due { parts.append(due) }
        if task.priorityName != "normal" { parts.append(task.priorityName.capitalized) }
        if let repeats = task.recurrence { parts.append("Repeats \(repeats)") }
        return parts.joined(separator: " · ")
    }
}

// MARK: Memory

struct MemoryView: View {
    @ObservedObject var model: AppModel
    @State private var query = ""
    @State private var newMemory = ""

    private var shown: [Memory] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? model.memories : model.memories.filter { $0.memory.lowercased().contains(q) }
    }

    var body: some View {
        NavStack {
            List {
                Section {
                    HStack {
                        TextField("Remember something", text: $newMemory).onSubmit(add).submitLabel(.done)
                        Button(action: add) { Image(systemName: "plus.circle.fill") }
                            .disabled(newMemory.trimmingCharacters(in: .whitespaces).isEmpty)
                            .accessibilityLabel("Save memory")
                    }
                } footer: {
                    Text("KYVON only saves what you ask it to, and refuses passwords and keys.")
                }
                if shown.isEmpty {
                    EmptyState(symbol: Theme.memorySymbol, title: query.isEmpty ? "No memories yet" : "No matches",
                               message: query.isEmpty ? "Say \"remember ...\" in a chat, or add one above." : "Try different words.")
                        .listRowBackground(Color.clear)
                }
                ForEach(shown) { memory in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(memory.memory)
                        Text("\(memory.category.capitalized)\(memory.importance > 1 ? " · Important" : "")")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    .swipeActions { Button("Delete", role: .destructive) { Task { await model.delete(memory) } } }
                }
            }
            .searchable(text: $query, prompt: "Search memories")
            .navigationTitle("Memory")
            .refreshable { await model.refreshMemories() }
            .background(Theme.background)
        }
    }

    private func add() {
        let text = newMemory
        newMemory = ""
        Task { await model.addMemory(text) }
    }
}

// MARK: Inbox

struct InboxView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        NavStack {
            List {
                if model.notifications.isEmpty {
                    EmptyState(symbol: "bell", title: "All caught up",
                               message: "Reminders and scheduled results from KYVON show up here.")
                        .listRowBackground(Color.clear)
                }
                ForEach(model.notifications) { note in
                    Button { Task { await model.markRead(note) } } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: note.read ? "circle" : "circle.fill")
                                .font(.caption2).foregroundStyle(Theme.accent).padding(.top, 5)
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(note.title).font(.headline)
                                if !note.body.isEmpty { Text(note.body).font(.subheadline).foregroundStyle(.secondary) }
                            }
                        }
                    }
                    .accessibilityLabel("\(note.read ? "" : "Unread. ")\(note.title). \(note.body)")
                }
            }
            .navigationTitle("Inbox")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Mark all read") { Task { await model.markAllRead() } }.disabled(model.unreadCount == 0)
                }
            }
            .refreshable { await model.refreshInbox() }
            .background(Theme.background)
        }
    }
}

// MARK: Settings

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @State private var confirmSignOut = false
    @State private var showDelete = false

    var body: some View {
        NavStack {
            Form {
                Section("Account") {
                    if case .signedIn(let user) = model.phase { LabeledRow(title: "Signed in as", value: user.username) }
                    if let url = model.client?.baseURL { LabeledRow(title: "Server", value: url.host ?? url.absoluteString) }
                }
                if let prefs = model.preferences {
                    Section("Assistant") {
                        choice("Response style", ["concise", "balanced", "detailed"], prefs.responseStyle) {
                            await model.updatePreferences(responseStyle: $0)
                        }
                        choice("Tone", ["default", "warm", "formal", "playful"], prefs.tone) {
                            await model.updatePreferences(tone: $0)
                        }
                        choice("Units", ["imperial", "metric"], prefs.units) {
                            await model.updatePreferences(units: $0)
                        }
                        Toggle("Speak replies", isOn: Binding(
                            get: { prefs.voiceReplies },
                            set: { value in Task { await model.updatePreferences(voiceReplies: value) } }))
                    }
                }
                if let usage = model.account?.usage {
                    planSection(usage)
                }
                if model.account?.hosted == true {
                    Section {
                        Button("Delete my account", role: .destructive) { showDelete = true }
                    } footer: {
                        Text("Permanently deletes your account and everything in it.")
                    }
                }
                Section("About") {
                    Link("Privacy policy", destination: LegalLinks.privacy)
                    Link("Terms of use", destination: LegalLinks.terms)
                    LabeledRow(title: "Version", value: Self.version)
                }
                Section {
                    Button("Sign out of this device", role: .destructive) { confirmSignOut = true }
                } footer: {
                    Text("Your chats, tasks and memories stay on your server.")
                }
                if let error = model.errorText { Section { ErrorBanner(text: error) } }
            }
            .navigationTitle("Settings")
            .refreshable { await model.refreshPreferences() }
            .sheet(isPresented: $showDelete) { DeleteAccountView(model: model, isPresented: $showDelete) }
            .confirmationDialog("Sign out of this device?", isPresented: $confirmSignOut, titleVisibility: .visible) {
                Button("Sign out", role: .destructive) { Task { await model.signOut() } }
            }
        }
    }

    @ViewBuilder private func planSection(_ usage: UsageSummary) -> some View {
        Section("Plan and usage") {
            LabeledRow(title: "Plan", value: usage.planName)
            if let email = model.account?.user.email {
                LabeledRow(title: "Email", value: usage.emailVerified ? email : "\(email) (not confirmed)")
            }
            if !usage.emailVerified {
                Button("Resend the confirmation email") { Task { await model.resendVerification() } }
            }
            if let limits = usage.limits {
                usageRow("Messages", used: usage.used.messages, limit: limits.messages)
                usageRow("AI usage", used: usage.used.tokens, limit: limits.tokens)
                usageRow("Voice clips", used: usage.used.voice, limit: limits.voice)
                usageRow("Web searches", used: usage.used.searches, limit: limits.searches)
            }
        }
    }

    private func usageRow(_ name: String, used: Int, limit: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(name)
                Spacer()
                Text("\(used) of \(limit)").foregroundStyle(.secondary)
            }
            ProgressView(value: Double(min(used, max(limit, 1))), total: Double(max(limit, 1)))
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(name): \(used) of \(limit) used")
    }

    private static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development"
    }

    private func choice(_ title: String, _ options: [String], _ current: String,
                        _ change: @escaping (String) async -> Void) -> some View {
        Picker(title, selection: Binding(get: { current }, set: { value in Task { await change(value) } })) {
            ForEach(options, id: \.self) { Text($0.capitalized).tag($0) }
        }
    }
}

// MARK: Delete account

/// Apple requires apps that offer account creation to let people delete the account inside the app.
struct DeleteAccountView: View {
    @ObservedObject var model: AppModel
    @Binding var isPresented: Bool
    @State private var password = ""
    @State private var working = false

    var body: some View {
        NavStack {
            Form {
                Section {
                    Text("This permanently deletes your account, chats, memories and tasks, and cancels any subscription. It cannot be undone.")
                    SecureField("Your password", text: $password).textContentType(.password)
                }
                if let error = model.errorText { Section { ErrorBanner(text: error) } }
                Section {
                    Button("Delete everything", role: .destructive) {
                        working = true
                        Task {
                            let done = await model.deleteAccount(password: password)
                            working = false
                            if done { isPresented = false }
                        }
                    }
                    .disabled(password.isEmpty || working)
                }
            }
            .navigationTitle("Delete account")
            .toolbar { ToolbarItem { Button("Cancel") { isPresented = false } } }
        }
    }
}
#endif
