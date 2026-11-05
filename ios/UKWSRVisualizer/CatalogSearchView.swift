import Foundation
import SwiftUI
import UIKit

struct CatalogSearchView: View {
    @ObservedObject var model: VisualizerViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Search", systemImage: "magnifyingglass") {
                            MetadataPill(text: model.catalogSearchSummary)
                        }
                        CatalogSearchField(text: criteriaBinding(\.text))
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Filters", systemImage: "line.3.horizontal.decrease.circle")

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogFilterMenu(
                                title: "Radar",
                                value: catalogRadarFilterText,
                                selection: criteriaBinding(\.radar)
                            ) {
                                Text("Any radar").tag("")
                                ForEach(model.catalogRadarOptions, id: \.self) { radar in
                                    Text(model.radarDisplayName(radar)).tag(radar)
                                }
                            }

                            CatalogFilterMenu(
                                title: "Year",
                                value: catalogYearFilterText,
                                selection: criteriaBinding(\.year)
                            ) {
                                Text("Any year").tag("")
                                ForEach(model.catalogYearOptions, id: \.self) { year in
                                    Text(year).tag(year)
                                }
                            }
                        }

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogDateField(title: "Start", text: criteriaBinding(\.startDate))
                            CatalogDateField(title: "End", text: criteriaBinding(\.endDate))
                        }

                        HStack(spacing: AppUI.controlSpacing) {
                            CatalogFilterMenu(
                                title: "Pulse",
                                value: catalogPulseFilterText,
                                selection: criteriaBinding(\.pulse)
                            ) {
                                Text("Any pulse").tag("")
                                ForEach(model.catalogPulseOptions, id: \.self) { pulse in
                                    Text(pulse).tag(pulse)
                                }
                            }

                            CatalogFilterMenu(
                                title: "Variable",
                                value: catalogQuantityFilterText,
                                selection: criteriaBinding(\.quantity)
                            ) {
                                Text("Any variable").tag("")
                                ForEach(model.catalogQuantityOptions, id: \.self) { quantity in
                                    Text(quantity).tag(quantity)
                                }
                            }
                        }

                        HStack(spacing: 8) {
                            Button {
                                model.setCatalogSearchToFirstDay()
                            } label: {
                                Label("Oldest", systemImage: "backward.end")
                            }
                            .disabled(model.catalogDateRange == nil)

                            Button {
                                model.setCatalogSearchToLatestDay()
                            } label: {
                                Label("Newest", systemImage: "forward.end")
                            }
                            .disabled(model.catalogDateRange == nil)

                            Button {
                                model.clearCatalogDateFilters()
                            } label: {
                                Label("Clear dates", systemImage: "xmark.circle")
                            }
                        }
                        .font(.caption)
                        .buttonStyle(.bordered)

                        Text(model.catalogCoverageStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                    .panelStyle()

                    VStack(alignment: .leading, spacing: 10) {
                        PanelHeader("Shortcuts", systemImage: "bolt")

                        CatalogActionButton(
                            title: "Closest radar, latest day",
                            subtitle: "Use this phone's location to pick the nearest radar.",
                            systemImage: "location.fill"
                        ) {
                            Task {
                                if await model.selectNearestRadarLatest() {
                                    dismiss()
                                }
                            }
                        }

                        CatalogActionButton(
                            title: "Latest available day",
                            subtitle: "Open the newest published catalog item.",
                            systemImage: "clock.arrow.circlepath"
                        ) {
                            if model.selectLatestPublishedDay() {
                                dismiss()
                            }
                        }

                        CatalogActionButton(
                            title: "Selected radar only",
                            subtitle: "Show days for the radar currently on screen.",
                            systemImage: "scope",
                            isEnabled: model.selectedItem != nil
                        ) {
                            model.setCatalogSearchToCurrentRadar()
                        }
                    }
                    .panelStyle()

                    LazyVStack(alignment: .leading, spacing: 8) {
                        PanelHeader("Results", systemImage: "list.bullet") {
                            if model.isLoadingCoverage {
                                ProgressView()
                                    .controlSize(.small)
                            }
                        }

                        if model.filteredCatalogItems.isEmpty {
                            Text("No matching catalog items")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        }

                        ForEach(model.filteredCatalogItems) { item in
                            Button {
                                model.selectCatalogItem(item)
                                dismiss()
                            } label: {
                                CatalogSearchRow(
                                    item: item,
                                    isSelected: model.selectedItemID == item.id,
                                    detailLine: model.catalogRowDetailText(for: item),
                                    facetLine: model.catalogRowFacetText(for: item),
                                    badges: model.catalogRowBadges(for: item)
                                )
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("CatalogSearchRow-\(item.id)")
                        }
                    }
                    .panelStyle()

                    if !model.recentSelections.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            PanelHeader("Recent", systemImage: "clock")

                            ForEach(Array(model.recentSelections.prefix(5))) { recent in
                                Button {
                                    if model.applyRecentSelection(recent) {
                                        dismiss()
                                    }
                                } label: {
                                    CatalogRecentRow(recent: recent)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .panelStyle()
                    }
                }
                .padding(12)
            }
            .background(Color(.systemGroupedBackground))
            .accessibilityIdentifier("CatalogSearchList")
            .navigationTitle("Select Data")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button {
                        model.resetCatalogSearch()
                    } label: {
                        Image(systemName: "arrow.counterclockwise")
                    }
                    .help("Reset catalog search")
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .accessibilityIdentifier("CatalogSearchDoneButton")
                }
            }
        }
        .presentationDetents([.medium, .large])
        .task {
            await model.loadCoverageForCurrentSearch()
        }
        .onChange(of: model.catalogSearch) { _ in
            Task { await model.loadCoverageForCurrentSearch() }
        }
    }

    private var catalogRadarFilterText: String {
        model.catalogSearch.radar.isEmpty ? "Any" : model.radarDisplayName(model.catalogSearch.radar)
    }

    private var catalogYearFilterText: String {
        model.catalogSearch.year.isEmpty ? "Any" : model.catalogSearch.year
    }

    private var catalogPulseFilterText: String {
        model.catalogSearch.pulse.isEmpty ? "Any" : model.catalogSearch.pulse
    }

    private var catalogQuantityFilterText: String {
        model.catalogSearch.quantity.isEmpty ? "Any" : model.catalogSearch.quantity
    }

    private func criteriaBinding<Value>(_ keyPath: WritableKeyPath<CatalogSearchCriteria, Value>) -> Binding<Value> {
        Binding(
            get: { model.catalogSearch[keyPath: keyPath] },
            set: { model.catalogSearch[keyPath: keyPath] = $0 }
        )
    }
}

private struct CatalogSearchField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
            TextField("Search catalog", text: $text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .accessibilityIdentifier("CatalogSearchTextField")
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear catalog search")
            }
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
    }
}

private struct CatalogFilterMenu<Content: View>: View {
    var title: String
    var value: String
    @Binding var selection: String
    var content: () -> Content

    init(
        title: String,
        value: String,
        selection: Binding<String>,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.value = value
        self._selection = selection
        self.content = content
    }

    var body: some View {
        Menu {
            Picker(title, selection: $selection) {
                content()
            }
        } label: {
            ControlTile(title: title, value: value, systemImage: "line.3.horizontal.decrease.circle", showsChevron: true)
        }
        .buttonStyle(.plain)
    }
}

private struct CatalogActionButton: View {
    var title: String
    var subtitle: String
    var systemImage: String
    var isEnabled = true
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: systemImage)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(.blue)
                    .frame(width: 30, height: 30)
                    .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(AppUI.valueFont)
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight, alignment: .leading)
            .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
            .overlay(
                RoundedRectangle(cornerRadius: AppUI.tileRadius)
                    .stroke(AppUI.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.5)
    }
}

private struct CatalogRecentRow: View {
    var recent: RecentCatalogSelection

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 28, height: 28)
                .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 2) {
                Text(recent.title)
                    .font(AppUI.valueFont)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(recent.detailText.isEmpty ? "Auto field selection" : recent.detailText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
        }
        .padding(.vertical, 6)
    }
}

private struct CatalogDateField: View {
    var title: String
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("YYYY-MM-DD", text: $text)
                .keyboardType(.numbersAndPunctuation)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(AppUI.valueFont)
                .accessibilityIdentifier("Catalog\(title.replacingOccurrences(of: " ", with: ""))Field")
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight, alignment: .leading)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
    }
}

private struct CatalogSearchRow: View {
    var item: CatalogItem
    var isSelected: Bool
    var detailLine: String
    var facetLine: String
    var badges: [String]

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(detailLine)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Text(facetLine)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if !badges.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 4) {
                            ForEach(badges, id: \.self) { badge in
                                Text(badge)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 6))
                            }
                        }
                    }
                    .scrollDisabled(true)
                }
            }
            Spacer()
            if isSelected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.tint)
            }
        }
        .contentShape(Rectangle())
        .padding(.vertical, 4)
        .accessibilityIdentifier("CatalogSearchRow-\(item.id)")
    }
}
