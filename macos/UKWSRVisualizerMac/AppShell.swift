import SwiftUI

struct AppShell: View {
    @ObservedObject var server: ServerController

    var body: some View {
        ZStack {
            if let url = server.viewerURL, server.isReady {
                WebContainer(url: url, reloadToken: server.reloadToken)
                    .ignoresSafeArea()
            }

            if !server.isReady {
                SplashView(server: server)
            }
        }
        .background(Color(red: 0.94, green: 0.97, blue: 0.98))
    }
}

private struct SplashView: View {
    @ObservedObject var server: ServerController

    var body: some View {
        VStack(spacing: 18) {
            logo
                .frame(width: 340, height: 340)

            Text("UK WSR Visualizer")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Color(red: 0.10, green: 0.16, blue: 0.20))

            Text(server.statusMessage)
                .font(.system(size: 15))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 560)

            if server.hasFailed {
                Button("Open Log") {
                    server.openLog()
                }
                .buttonStyle(.borderedProminent)
            } else {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .padding(40)
    }

    @ViewBuilder
    private var logo: some View {
        if let image = server.logoImage {
            Image(nsImage: image)
                .resizable()
                .scaledToFit()
        } else {
            Image(systemName: "dot.radiowaves.left.and.right")
                .resizable()
                .scaledToFit()
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.teal)
                .padding(70)
        }
    }
}
