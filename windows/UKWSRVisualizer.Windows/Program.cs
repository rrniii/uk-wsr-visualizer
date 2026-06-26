using System.Diagnostics;
using System.Drawing;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace UKWSRVisualizer.Windows;

internal static class Program
{
    private const string AppName = "UK WSR Visualizer";
    private const string BuildVersion = "windows-beta-20260626";
    private const string RemoteBase = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public";
    private const string RemoteCatalog = RemoteBase + "/uk-radar/catalog/inventory/catalog.json";

    [STAThread]
    private static async Task<int> Main(string[] args)
    {
        LauncherConfig config = LauncherConfig.Create();
        if (args.Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            return await RunSelfTest(config);
        }

        ApplicationConfiguration.Initialize();
        if (!WebView2RuntimeAvailable(out string runtimeMessage))
        {
            MessageBox.Show(
                runtimeMessage,
                "WebView2 Runtime Required",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 2;
        }

        Application.Run(new MainWindow(config));
        return 0;
    }

    private static async Task<int> RunSelfTest(LauncherConfig config)
    {
        using ServerProcess server = new(config);
        try
        {
            server.Start();
            await ServerHealth.WaitForReady(config.BaseUrl, TimeSpan.FromSeconds(90));
            string status = await ServerHealth.GetStatus(config.BaseUrl);
            Console.WriteLine(status);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            Console.Error.WriteLine("Log: " + config.LogFile);
            return 1;
        }
    }

    private static bool WebView2RuntimeAvailable(out string message)
    {
        try
        {
            _ = CoreWebView2Environment.GetAvailableBrowserVersionString();
            message = "";
            return true;
        }
        catch
        {
            message = "UK WSR Visualizer needs the Microsoft Edge WebView2 Runtime. Install the Evergreen WebView2 Runtime from Microsoft, then reopen the app:\n\nhttps://developer.microsoft.com/microsoft-edge/webview2/";
            return false;
        }
    }

    internal sealed class LauncherConfig
    {
        private LauncherConfig(string appRoot, string supportDir, int port)
        {
            AppRoot = appRoot;
            SupportDir = supportDir;
            Port = port;
            DataDir = Path.Combine(SupportDir, "data");
            LogFile = Path.Combine(SupportDir, "uk-wsr-visualizer.log");
            ServerPidFile = Path.Combine(SupportDir, "server.pid");
            ServerExe = Path.Combine(AppRoot, "server", "uk-wsr-visualizer-server.exe");
            LogoFile = Path.Combine(AppRoot, "resources", "UKWSRVisualizer.png");
            BaseUrl = $"http://127.0.0.1:{Port}";
            WindowUrl = $"{BaseUrl}/?v={BuildVersion}";
        }

        public string AppRoot { get; }
        public string SupportDir { get; }
        public string DataDir { get; }
        public string LogFile { get; }
        public string ServerPidFile { get; }
        public string ServerExe { get; }
        public string LogoFile { get; }
        public int Port { get; }
        public string BaseUrl { get; }
        public string WindowUrl { get; }

        public static LauncherConfig Create()
        {
            string appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string supportDir = Path.Combine(localAppData, AppName);
            Directory.CreateDirectory(supportDir);
            Directory.CreateDirectory(Path.Combine(supportDir, "data"));

            int requested = ReadPort();
            int port = ResolvePort(supportDir, requested);
            return new LauncherConfig(appRoot, supportDir, port);
        }

        private static int ReadPort()
        {
            string? value = Environment.GetEnvironmentVariable("UK_WSR_VISUALIZER_WINDOWS_PORT");
            return int.TryParse(value, out int port) && port > 0 ? port : 8765;
        }

        private static int ResolvePort(string supportDir, int requested)
        {
            if (PortAvailable(requested))
            {
                return requested;
            }

            TryStopSavedServer(Path.Combine(supportDir, "server.pid"));
            if (PortAvailable(requested))
            {
                return requested;
            }

            for (int port = 8766; port <= 8785; port++)
            {
                if (PortAvailable(port))
                {
                    return port;
                }
            }
            throw new InvalidOperationException("No free local port found in 8765-8785.");
        }

        private static bool PortAvailable(int port)
        {
            try
            {
                using TcpListener listener = new(IPAddress.Loopback, port);
                listener.Start();
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void TryStopSavedServer(string pidFile)
        {
            try
            {
                if (!File.Exists(pidFile) || !int.TryParse(File.ReadAllText(pidFile).Trim(), out int pid))
                {
                    return;
                }
                Process process = Process.GetProcessById(pid);
                string name = process.ProcessName.ToLowerInvariant();
                if (!name.Contains("uk-wsr-visualizer-server") && !name.Contains("python"))
                {
                    return;
                }
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
            catch
            {
                // A stale pid file should not block startup.
            }
        }
    }

    internal sealed class ServerProcess : IDisposable
    {
        private readonly LauncherConfig config;
        private Process? process;

        public ServerProcess(LauncherConfig config)
        {
            this.config = config;
        }

        public void Start()
        {
            if (!File.Exists(config.ServerExe))
            {
                throw new FileNotFoundException("Bundled server executable is missing.", config.ServerExe);
            }

            Directory.CreateDirectory(config.DataDir);
            Directory.CreateDirectory(Path.GetDirectoryName(config.LogFile)!);
            File.AppendAllText(config.LogFile, $"{DateTimeOffset.UtcNow:O} starting Windows server on {config.BaseUrl}{Environment.NewLine}");

            ProcessStartInfo startInfo = new()
            {
                FileName = config.ServerExe,
                Arguments = $"api --host 127.0.0.1 --port {config.Port}",
                WorkingDirectory = config.AppRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            startInfo.Environment["UK_WSR_VISUALIZER_DATA_DIR"] = config.DataDir;
            startInfo.Environment["UK_WSR_VISUALIZER_CATALOG"] = Path.Combine(config.DataDir, "catalog.json");
            startInfo.Environment["UK_WSR_VISUALIZER_REMOTE_CATALOG_URL"] = RemoteCatalog;
            startInfo.Environment["UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE"] = RemoteBase;
            startInfo.Environment["UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS"] = "3600";
            startInfo.Environment["UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES"] = "26843545600";

            process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, args) => AppendLog(args.Data);
            process.ErrorDataReceived += (_, args) => AppendLog(args.Data);
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            File.WriteAllText(config.ServerPidFile, process.Id.ToString());
        }

        public void Dispose()
        {
            try
            {
                if (process is { HasExited: false })
                {
                    File.AppendAllText(config.LogFile, $"{DateTimeOffset.UtcNow:O} stopping Windows server pid {process.Id}{Environment.NewLine}");
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(5000);
                }
            }
            catch
            {
                // Best-effort shutdown on app close.
            }
            process?.Dispose();
        }

        private void AppendLog(string? line)
        {
            if (string.IsNullOrEmpty(line))
            {
                return;
            }
            try
            {
                File.AppendAllText(config.LogFile, $"{DateTimeOffset.UtcNow:O} {line}{Environment.NewLine}");
            }
            catch
            {
                // Logging failure should not bring down the app window.
            }
        }
    }

    internal static class ServerHealth
    {
        public static async Task WaitForReady(string baseUrl, TimeSpan timeout)
        {
            using HttpClient client = new() { Timeout = TimeSpan.FromSeconds(2) };
            DateTimeOffset deadline = DateTimeOffset.UtcNow + timeout;
            while (DateTimeOffset.UtcNow < deadline)
            {
                try
                {
                    HttpResponseMessage response = await client.GetAsync(baseUrl + "/api/ready");
                    if (response.IsSuccessStatusCode)
                    {
                        return;
                    }
                }
                catch
                {
                    // Server is still starting.
                }
                await Task.Delay(750);
            }
            throw new TimeoutException("The local UK WSR Visualizer server did not become ready.");
        }

        public static async Task<string> GetStatus(string baseUrl)
        {
            using HttpClient client = new() { Timeout = TimeSpan.FromSeconds(10) };
            return await client.GetStringAsync(baseUrl + "/api/status");
        }
    }

    internal sealed class MainWindow : Form
    {
        private readonly LauncherConfig config;
        private readonly WebView2 webView = new() { Dock = DockStyle.Fill, Visible = false };
        private readonly Panel splash = new() { Dock = DockStyle.Fill, BackColor = Color.FromArgb(240, 247, 249) };
        private readonly Label status = new() { AutoSize = true, Text = "Starting local radar viewer..." };
        private ServerProcess? server;

        public MainWindow(LauncherConfig config)
        {
            this.config = config;
            Text = AppName;
            Width = 1440;
            Height = 940;
            MinimumSize = new Size(1100, 720);
            StartPosition = FormStartPosition.CenterScreen;
            BuildSplash();
            Controls.Add(webView);
            Controls.Add(splash);
            webView.NavigationCompleted += (_, _) =>
            {
                splash.Visible = false;
                webView.Visible = true;
            };
            Shown += async (_, _) => await StartAsync();
            FormClosed += (_, _) => server?.Dispose();
        }

        private void BuildSplash()
        {
            TableLayoutPanel layout = new()
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                RowCount = 3,
            };
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));

            FlowLayoutPanel stack = new()
            {
                FlowDirection = FlowDirection.TopDown,
                AutoSize = true,
                Anchor = AnchorStyles.None,
                WrapContents = false,
            };

            PictureBox logo = new()
            {
                Width = 340,
                Height = 340,
                SizeMode = PictureBoxSizeMode.Zoom,
                Image = File.Exists(config.LogoFile) ? Image.FromFile(config.LogoFile) : null,
                Margin = new Padding(0, 0, 0, 18),
            };
            Label title = new()
            {
                Text = AppName,
                AutoSize = true,
                Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 24, FontStyle.Bold),
                ForeColor = Color.FromArgb(25, 40, 51),
                Margin = new Padding(0, 0, 0, 14),
            };
            status.Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 11, FontStyle.Regular);
            status.ForeColor = Color.FromArgb(91, 103, 116);

            stack.Controls.Add(logo);
            stack.Controls.Add(title);
            stack.Controls.Add(status);
            layout.Controls.Add(new Panel(), 0, 0);
            layout.Controls.Add(stack, 0, 1);
            layout.Controls.Add(new Panel(), 0, 2);
            splash.Controls.Add(layout);
        }

        private async Task StartAsync()
        {
            try
            {
                server = new ServerProcess(config);
                server.Start();
                await ServerHealth.WaitForReady(config.BaseUrl, TimeSpan.FromMinutes(10));
                status.Text = "Loading radar interface...";
                await webView.EnsureCoreWebView2Async();
                webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
                webView.Source = new Uri(config.WindowUrl);
            }
            catch (Exception ex)
            {
                status.Text = "UK WSR Visualizer did not start. Opening the log.";
                File.AppendAllText(config.LogFile, $"{DateTimeOffset.UtcNow:O} {ex}{Environment.NewLine}");
                MessageBox.Show(
                    $"UK WSR Visualizer did not start. The log is at:\n\n{config.LogFile}",
                    AppName,
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                TryOpenLog();
            }
        }

        private void TryOpenLog()
        {
            try
            {
                Process.Start(new ProcessStartInfo(config.LogFile) { UseShellExecute = true });
            }
            catch
            {
                // The dialog already showed the log path.
            }
        }
    }
}
