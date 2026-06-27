import SwiftUI
import UIKit

struct ContentView: View {
    @AppStorage("serverURLString") private var serverURLString: String = ServerSettings.defaultURLString
    @StateObject private var browserState = BrowserState()
    @State private var showingSettings = false
    @State private var browserIdentity = UUID()

    private var currentURL: URL {
        ServerSettings.normalizedURL(from: serverURLString) ?? ServerSettings.defaultURL
    }

    var body: some View {
        NavigationStack {
            VisualizerWebView(url: currentURL, state: browserState)
                .id(browserIdentity)
                .ignoresSafeArea(edges: .bottom)
                .safeAreaInset(edge: .top, spacing: 0) {
                    StatusStrip(state: browserState)
                }
                .navigationTitle(browserState.title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItemGroup(placement: .navigationBarLeading) {
                        Button {
                            browserState.goBack?()
                        } label: {
                            Image(systemName: "chevron.left")
                        }
                        .disabled(!browserState.canGoBack)

                        Button {
                            browserState.goForward?()
                        } label: {
                            Image(systemName: "chevron.right")
                        }
                        .disabled(!browserState.canGoForward)
                    }

                    ToolbarItemGroup(placement: .navigationBarTrailing) {
                        Button {
                            browserState.reload?()
                        } label: {
                            Image(systemName: "arrow.clockwise")
                        }

                        Button {
                            UIApplication.shared.open(currentURL)
                        } label: {
                            Image(systemName: "safari")
                        }

                        Button {
                            showingSettings = true
                        } label: {
                            Image(systemName: "gearshape")
                        }
                    }
                }
                .sheet(isPresented: $showingSettings) {
                    ServerSettingsView(serverURLString: $serverURLString) {
                        browserIdentity = UUID()
                    }
                }
        }
    }
}

private struct StatusStrip: View {
    @ObservedObject var state: BrowserState

    var body: some View {
        if state.isLoading || state.errorMessage != nil {
            HStack(spacing: 10) {
                if state.isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
                Text(state.errorMessage ?? "Loading")
                    .font(.footnote)
                    .lineLimit(2)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.regularMaterial)
        }
    }
}

private struct ServerSettingsView: View {
    @Binding var serverURLString: String
    let onSave: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draftURL: String
    @State private var validationMessage: String?

    init(serverURLString: Binding<String>, onSave: @escaping () -> Void) {
        _serverURLString = serverURLString
        _draftURL = State(initialValue: serverURLString.wrappedValue)
        self.onSave = onSave
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("http://130.246.214.121", text: $draftURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()

                    if let validationMessage {
                        Text(validationMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    Button("Use hosted server") {
                        draftURL = ServerSettings.defaultURLString
                    }

                    Button("Use local development server") {
                        draftURL = "http://YOUR-MAC-IP:8000"
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        guard let normalized = ServerSettings.normalizedURLString(from: draftURL) else {
                            validationMessage = "Enter a valid http or https URL."
                            return
                        }
                        serverURLString = normalized
                        onSave()
                        dismiss()
                    }
                }
            }
        }
    }
}
