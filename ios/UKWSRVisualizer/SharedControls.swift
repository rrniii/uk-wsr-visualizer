import SwiftUI
import UIKit

enum AppUI {
    static let panelRadius: CGFloat = 8
    static let tileRadius: CGFloat = 8
    static let tileHeight: CGFloat = 60
    static let scanHeaderHeight: CGFloat = 56
    static let hairlineOpacity = 0.28
    static let sectionSpacing: CGFloat = 10
    static let controlSpacing: CGFloat = 8

    static var panelBackground: Color { Color(.secondarySystemGroupedBackground) }
    static var tileBackground: Color { Color(.tertiarySystemGroupedBackground) }
    static var insetBackground: Color { Color(.quaternarySystemFill) }
    static var hairline: Color { Color(.separator).opacity(hairlineOpacity) }

    static var valueFont: Font { .body.weight(.semibold) }
    static var labelFont: Font { .caption2.weight(.semibold) }
    static var metadataFont: Font { .caption.monospacedDigit() }
}

struct PanelHeader<Trailing: View>: View {
    var title: String
    var systemImage: String
    var trailing: Trailing

    init(
        _ title: String,
        systemImage: String,
        @ViewBuilder trailing: () -> Trailing = { EmptyView() }
    ) {
        self.title = title
        self.systemImage = systemImage
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 8) {
            Label(title, systemImage: systemImage)
                .font(.headline)
            Spacer(minLength: 8)
            trailing
        }
    }
}

struct MetadataPill: View {
    var text: String

    var body: some View {
        Text(text)
            .font(AppUI.metadataFont)
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(AppUI.insetBackground, in: Capsule())
    }
}

struct ControlTile: View {
    var title: String
    var value: String
    var systemImage: String
    var showsChevron = true

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 28, height: 28)
                .background(AppUI.insetBackground, in: RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 2) {
                Text(title.uppercased())
                    .font(AppUI.labelFont)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(AppUI.valueFont)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.68)
            }

            Spacer(minLength: 4)

            if showsChevron {
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, minHeight: AppUI.tileHeight)
        .background(AppUI.tileBackground, in: RoundedRectangle(cornerRadius: AppUI.tileRadius))
        .overlay(
            RoundedRectangle(cornerRadius: AppUI.tileRadius)
                .stroke(AppUI.hairline, lineWidth: 1)
        )
    }
}

extension View {
    func panelStyle() -> some View {
        self
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppUI.panelBackground, in: RoundedRectangle(cornerRadius: AppUI.panelRadius))
            .overlay(
                RoundedRectangle(cornerRadius: AppUI.panelRadius)
                    .stroke(AppUI.hairline, lineWidth: 1)
            )
    }
}
