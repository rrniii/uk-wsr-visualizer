import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct ProjectsWorkspaceView: View {
    @ObservedObject var model: VisualizerViewModel
    @ObservedObject var store: WorkspaceProjectStore
    @State private var title = "Radar project"
    @State private var isImporting = false
    @State private var manifestURL: URL?
    @State private var citationURL: URL?
    @State private var message = ""

    var body: some View {
        NavigationStack {
            List {
                Section("Current workspace") {
                    TextField("Project title", text: $title)
                    HStack {
                        Button {
                            saveCurrentProject()
                        } label: {
                            Label("Save project", systemImage: "folder.badge.plus")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.selectedItem == nil)

                        Button {
                            isImporting = true
                        } label: {
                            Label("Import", systemImage: "square.and.arrow.down")
                        }
                        .buttonStyle(.bordered)
                    }
                }

                Section("Saved projects") {
                    if store.projects.isEmpty {
                        Label("No saved projects", systemImage: "folder")
                            .font(.headline)
                        Text("Save the current radar workspace or import a desktop project file.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    ForEach(store.projects) { project in
                        VStack(alignment: .leading, spacing: 7) {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(project.session.title).font(.headline)
                                    Text("\(project.session.state.radar) · \(project.session.state.start) · \(project.session.state.quantity)")
                                        .font(.caption.monospacedDigit())
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Load") {
                                    Task {
                                        await model.applyProjectState(project.session.state)
                                        message = "Loaded \(project.session.title)."
                                    }
                                }
                                .buttonStyle(.borderedProminent)
                                ShareLink(item: store.fileURL(for: project)) {
                                    Image(systemName: "square.and.arrow.up")
                                }
                                Button(role: .destructive) {
                                    try? store.delete(project)
                                } label: {
                                    Image(systemName: "trash")
                                }
                            }
                        }
                    }
                }

                Section("Provenance & citation") {
                    Button("Create artifact manifest") { createManifest() }
                        .disabled(model.selectedItem == nil)
                    if let manifestURL {
                        ShareLink(item: manifestURL) {
                            Label("Share manifest", systemImage: "doc.badge.arrow.up")
                        }
                    }
                    Button("Create citation record") { createCitation() }
                    if let citationURL {
                        ShareLink(item: citationURL) {
                            Label("Share citation", systemImage: "quote.bubble")
                        }
                    }
                    if let url = URL(string: model.selectedSourceURLString), !model.selectedSourceURLString.isEmpty {
                        ShareLink(item: url) {
                            Label("Share source-object URL", systemImage: "link")
                        }
                    }
                    Text(CitationPayload().userInstruction)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !message.isEmpty || !store.statusMessage.isEmpty {
                    Section("Status") {
                        Text(message.isEmpty ? store.statusMessage : message)
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("Projects & Provenance")
            .fileImporter(isPresented: $isImporting, allowedContentTypes: [.json]) { result in
                do {
                    let project = try store.importProject(from: result.get())
                    title = project.session.title
                    message = "Imported \(project.session.title)."
                } catch {
                    message = error.localizedDescription
                }
            }
        }
        .accessibilityIdentifier("ProjectsWorkspace")
    }

    private func saveCurrentProject() {
        do {
            _ = try store.save(.make(title: title, model: model))
            message = "Saved \(title)."
        } catch {
            message = error.localizedDescription
        }
    }

    private func createManifest() {
        do {
            manifestURL = try WorkspaceJSONExporter.writeManifest(
                ArtifactManifest.make(format: "screen_view", coordinateMode: "screen_view", model: model)
            )
            message = "Artifact manifest is ready to share."
        } catch {
            message = error.localizedDescription
        }
    }

    private func createCitation() {
        do {
            citationURL = try WorkspaceJSONExporter.writeCitation()
            message = "Citation record is ready to share."
        } catch {
            message = error.localizedDescription
        }
    }
}
