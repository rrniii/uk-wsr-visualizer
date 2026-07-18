using System.Collections.Generic;
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
    private const string RemoteCatalog = RemoteBase + "/ukmo-nimrod/catalog/pvol/catalog.json";
    private const string PreDualRemoteCatalog = RemoteBase + "/ukmo-nimrod-pre-dual-pol/catalog/pvol/catalog.json";
    private const int DefaultPort = 8765;
    private const int FirstFallbackPort = 8766;
    private const int LastFallbackPort = 8785;
    private static readonly TimeSpan ReadyTimeout = TimeSpan.FromMinutes(2);

    [STAThread]
    private static int Main(string[] args)
    {
        LauncherConfig config = LauncherConfig.Create();
        if (args.Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            return RunSelfTest(config).GetAwaiter().GetResult();
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
        try
        {
            using ServerProcess server = await StartServerWithRetry(config, TimeSpan.FromSeconds(90));
            string status = await ServerHealth.GetStatus(server.Config.BaseUrl);
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

    private static async Task<ServerProcess> StartServerWithRetry(
        LauncherConfig initialConfig,
        TimeSpan timeout,
        Action<LauncherConfig>? onConfigChanged = null,
        Action<string>? onStatus = null)
    {
        LauncherConfig activeConfig = initialConfig;
        Exception? firstFailure = null;

        for (int attempt = 1; attempt <= 2; attempt++)
        {
            ServerProcess server = new(activeConfig);
            try
            {
                onStatus?.Invoke(attempt == 1 ? "Starting local radar server..." : "Retrying local radar server on another port...");
                server.Start();
                await ServerHealth.WaitForReady(activeConfig.BaseUrl, timeout, server);
                onStatus?.Invoke("Loading radar interface...");
                return server;
            }
            catch (Exception ex) when (attempt == 1)
            {
                firstFailure = ex;
                server.KillAndClearPidFile($"startup attempt {attempt} failed: {ex.Message}");
                activeConfig = activeConfig.WithPort(LauncherConfig.ResolveFallbackPort(activeConfig.Port));
                onConfigChanged?.Invoke(activeConfig);
                continue;
            }
            catch (Exception ex)
            {
                server.KillAndClearPidFile($"startup attempt {attempt} failed: {ex.Message}");
                throw new InvalidOperationException(
                    $"The local UK WSR Visualizer server did not become ready after a retry. First failure: {firstFailure?.Message}. Last failure: {ex.Message}",
                    ex);
            }
        }

        throw new InvalidOperationException("The local UK WSR Visualizer server did not become ready.");
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
            return int.TryParse(value, out int port) && port > 0 ? port : DefaultPort;
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

            for (int port = FirstFallbackPort; port <= LastFallbackPort; port++)
            {
                if (PortAvailable(port))
                {
                    return port;
                }
            }
            throw new InvalidOperationException("No free local port found in 8765-8785.");
        }

        public LauncherConfig WithPort(int port) => new(AppRoot, SupportDir, port);

        public static int ResolveFallbackPort(int currentPort)
        {
            for (int port = FirstFallbackPort; port <= LastFallbackPort; port++)
            {
                if (port != currentPort && PortAvailable(port))
                {
                    return port;
                }
            }
            throw new InvalidOperationException("No free retry port found in 8766-8785.");
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
                File.Delete(pidFile);
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
        private readonly Queue<string> recentOutput = new();
        private Process? process;

        public ServerProcess(LauncherConfig config)
        {
            this.config = config;
        }

        public LauncherConfig Config => config;
        public bool HasExited => process is { HasExited: true };
        public int? ExitCode => process is { HasExited: true } ? process.ExitCode : null;
        public int? ProcessId => process?.Id;
        public string RecentOutput => string.Join(Environment.NewLine, recentOutput.ToArray());

        public void Start()
        {
            if (!File.Exists(config.ServerExe))
            {
                throw new FileNotFoundException("Bundled server executable is missing.", config.ServerExe);
            }

            Directory.CreateDirectory(config.DataDir);
            Directory.CreateDirectory(Path.GetDirectoryName(config.LogFile)!);
            AppendLauncherLog("starting Windows server");
            AppendLauncherLog($"app_version={BuildVersion}");
            AppendLauncherLog($"server_exe={config.ServerExe}");
            AppendLauncherLog($"working_dir={config.AppRoot}");
            AppendLauncherLog($"selected_port={config.Port}");
            AppendLauncherLog($"base_url={config.BaseUrl}");
            AppendLauncherLog($"remote_catalog={RemoteCatalog}");
            AppendLauncherLog($"pre_dual_remote_catalog={PreDualRemoteCatalog}");
            AppendLauncherLog($"data_dir={config.DataDir}");
            AppendLauncherLog($"cache_max_bytes=26843545600");

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
            startInfo.Environment["UK_WSR_VISUALIZER_PRE_DUAL_POL_REMOTE_CATALOG_URL"] = PreDualRemoteCatalog;
            startInfo.Environment["UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE"] = RemoteBase;
            startInfo.Environment["UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS"] = "0";
            startInfo.Environment["UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES"] = "26843545600";

            process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, args) => AppendLog(args.Data);
            process.ErrorDataReceived += (_, args) => AppendLog(args.Data);
            if (!process.Start())
            {
                throw new InvalidOperationException("Bundled server process did not start.");
            }
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            File.WriteAllText(config.ServerPidFile, process.Id.ToString());
            AppendLauncherLog($"started Windows server pid {process.Id}");
        }

        public void KillAndClearPidFile(string reason)
        {
            try
            {
                if (process is { HasExited: false })
                {
                    AppendLauncherLog($"{reason}; stopping Windows server pid {process.Id}");
                    process.Kill(entireProcessTree: true);
                    process.WaitForExit(5000);
                }
                else if (process is { HasExited: true })
                {
                    AppendLauncherLog($"{reason}; Windows server already exited with code {process.ExitCode}");
                }
                if (File.Exists(config.ServerPidFile))
                {
                    File.Delete(config.ServerPidFile);
                }
            }
            catch
            {
                // Best-effort shutdown on app close.
            }
        }

        public void Dispose()
        {
            KillAndClearPidFile("disposing launcher");
            process?.Dispose();
        }

        private void AppendLauncherLog(string line)
        {
            try
            {
                File.AppendAllText(config.LogFile, $"{DateTimeOffset.UtcNow:O} {line}{Environment.NewLine}");
            }
            catch
            {
                // Logging failure should not block startup.
            }
        }

        private void AppendLog(string? line)
        {
            if (string.IsNullOrEmpty(line))
            {
                return;
            }
            recentOutput.Enqueue(line);
            while (recentOutput.Count > 20)
            {
                recentOutput.Dequeue();
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
        public static async Task WaitForReady(string baseUrl, TimeSpan timeout, ServerProcess? serverProcess = null)
        {
            using HttpClient client = new() { Timeout = TimeSpan.FromSeconds(2) };
            DateTimeOffset deadline = DateTimeOffset.UtcNow + timeout;
            string lastError = "";
            while (DateTimeOffset.UtcNow < deadline)
            {
                if (serverProcess is { HasExited: true })
                {
                    string output = serverProcess.RecentOutput;
                    string suffix = string.IsNullOrWhiteSpace(output) ? "" : $" Recent server output: {output}";
                    throw new InvalidOperationException($"The local server exited before it became ready (exit code {serverProcess.ExitCode}).{suffix}");
                }
                try
                {
                    HttpResponseMessage response = await client.GetAsync(baseUrl + "/api/ready");
                    if (response.IsSuccessStatusCode)
                    {
                        return;
                    }
                    lastError = $"HTTP {(int)response.StatusCode} {response.ReasonPhrase}";
                }
                catch (Exception ex)
                {
                    lastError = ex.Message;
                }
                await Task.Delay(750);
            }
            throw new TimeoutException($"The local UK WSR Visualizer server did not become ready. Last readiness error: {lastError}");
        }

        public static async Task<string> GetStatus(string baseUrl)
        {
            using HttpClient client = new() { Timeout = TimeSpan.FromSeconds(10) };
            return await client.GetStringAsync(baseUrl + "/api/status");
        }
    }

    internal sealed class MainWindow : Form
    {
        private LauncherConfig config;
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
                Font = new Font(FontFamily.GenericSansSerif, 24, FontStyle.Bold),
                ForeColor = Color.FromArgb(25, 40, 51),
                Margin = new Padding(0, 0, 0, 14),
            };
            status.Font = new Font(FontFamily.GenericSansSerif, 11, FontStyle.Regular);
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
                server = await StartServerWithRetry(
                    config,
                    ReadyTimeout,
                    updatedConfig => config = updatedConfig,
                    message => status.Text = message);
                await webView.EnsureCoreWebView2Async();
                webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
                webView.Source = new Uri(server.Config.WindowUrl);
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
