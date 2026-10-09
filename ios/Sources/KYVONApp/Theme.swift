#if canImport(SwiftUI)
import SwiftUI

/// The app's look in one place. The app is dark-only (see `RootView`); colours are chosen for
/// contrast against `background`, and status is never conveyed by colour alone.
enum Theme {
    static let background = Color(red: 0.06, green: 0.07, blue: 0.09)
    static let card = Color(red: 0.09, green: 0.10, blue: 0.13)
    static let accent = Color(red: 0.43, green: 0.66, blue: 1.0)
    static let userBubble = Color(red: 0.16, green: 0.29, blue: 0.48)
    static let assistantBubble = Color(red: 0.11, green: 0.13, blue: 0.16)
    static let warning = Color(red: 0.90, green: 0.77, blue: 0.35)
    static let danger = Color(red: 0.88, green: 0.42, blue: 0.42)
    static let success = Color(red: 0.37, green: 0.75, blue: 0.54)
    static let corner: CGFloat = 12
}

/// Where the policies live. They must be public web pages (App Store Connect asks for the privacy
/// policy URL). Update these if the documents move, for example to a site you host.
enum LegalLinks {
    static let privacy = URL(string: "https://github.com/temcwilliams/jarvis-assistant/blob/main/docs/legal/PRIVACY_POLICY.md")!
    static let terms = URL(string: "https://github.com/temcwilliams/jarvis-assistant/blob/main/docs/legal/TERMS_OF_USE.md")!
}

/// A rounded card row used by every list so the screens feel like one app.
struct CardRow<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner))
    }
}

/// Shown instead of an empty list: an invitation, not an apology.
struct EmptyState: View {
    let symbol: String
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol).font(.largeTitle).foregroundStyle(.secondary).accessibilityHidden(true)
            Text(title).font(.headline)
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(32)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// A short error line shown above content. It carries an icon and text, not just colour.
struct ErrorBanner: View {
    let text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .font(.footnote)
            .foregroundStyle(Theme.danger)
            .padding(.horizontal)
            .accessibilityLabel("Error: \(text)")
    }
}

extension View {
    /// iOS-only text-field behaviour, kept in one place so the package still builds on macOS.
    @ViewBuilder func plainTextInput(url: Bool = false) -> some View {
        #if os(iOS)
        if url {
            self.textContentType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        } else {
            self.textInputAutocapitalization(.never).autocorrectionDisabled()
        }
        #else
        self.autocorrectionDisabled()
        #endif
    }

    @ViewBuilder func inlineNavigationTitle() -> some View {
        #if os(iOS)
        self.navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
}
/// `NavigationStack` on iOS 16+/macOS 13+, `NavigationView` before that (the app supports iOS 15).
struct NavStack<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        if #available(iOS 16, macOS 13, *) {
            NavigationStack { content }
        } else {
            #if os(iOS)
            NavigationView { content }.navigationViewStyle(.stack)
            #else
            NavigationView { content }
            #endif
        }
    }
}

/// A "Title ........ value" row (`LabeledContent` needs iOS 16).
struct LabeledRow: View {
    let title: String
    let value: String
    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(value).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}

extension Theme {
    /// The "brain" symbol needs iOS 16; older systems get a bookmark.
    static var memorySymbol: String {
        if #available(iOS 16, macOS 13, *) { return "brain" } else { return "bookmark" }
    }
}

#endif
