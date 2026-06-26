#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface UKWSRWindowController : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSURL *targetURL;
@property(nonatomic, strong) NSURL *readyURL;
@property(nonatomic, copy) NSString *logoPath;
@property(nonatomic, copy) NSString *logPath;
@property(nonatomic) NSTimeInterval timeoutSeconds;
@property(nonatomic, strong) NSDate *startedAt;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSView *splashView;
@property(nonatomic, strong) NSTextField *statusLabel;
@end

@implementation UKWSRWindowController

- (instancetype)initWithURL:(NSURL *)url logoPath:(NSString *)logoPath logPath:(NSString *)logPath timeout:(NSTimeInterval)timeout {
    self = [super init];
    if (self) {
        _targetURL = url;
        _readyURL = [NSURL URLWithString:@"/api/ready" relativeToURL:url].absoluteURL;
        _logoPath = [logoPath copy];
        _logPath = [logPath copy];
        _timeoutSeconds = timeout;
        _startedAt = [NSDate date];
    }
    return self;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [self buildMenu];
    [self buildWindow];
    [NSApp activateIgnoringOtherApps:YES];
    [self pollServer];
    self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:0.75 target:self selector:@selector(pollServer) userInfo:nil repeats:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

- (void)buildMenu {
    NSMenu *mainMenu = [[NSMenu alloc] initWithTitle:@""];
    NSMenuItem *appItem = [[NSMenuItem alloc] initWithTitle:@"" action:nil keyEquivalent:@""];
    [mainMenu addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@""];
    [appMenu addItemWithTitle:@"Quit UK WSR Visualizer" action:@selector(terminate:) keyEquivalent:@"q"];
    appItem.submenu = appMenu;
    NSApp.mainMenu = mainMenu;
}

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 1440, 940);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                              styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
    self.window.title = @"UK WSR Visualizer";
    self.window.minSize = NSMakeSize(1100, 720);
    [self.window center];

    WKWebViewConfiguration *config = [[WKWebViewConfiguration alloc] init];
    config.preferences.javaScriptCanOpenWindowsAutomatically = YES;
    config.websiteDataStore = [WKWebsiteDataStore nonPersistentDataStore];
    self.webView = [[WKWebView alloc] initWithFrame:frame configuration:config];
    self.webView.navigationDelegate = self;
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.hidden = YES;

    self.splashView = [[NSView alloc] initWithFrame:frame];
    self.splashView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.splashView.wantsLayer = YES;
    self.splashView.layer.backgroundColor = [NSColor colorWithCalibratedRed:0.94 green:0.97 blue:0.98 alpha:1.0].CGColor;

    NSImageView *imageView = [[NSImageView alloc] initWithFrame:NSZeroRect];
    imageView.image = [[NSImage alloc] initWithContentsOfFile:self.logoPath];
    imageView.imageScaling = NSImageScaleProportionallyUpOrDown;
    imageView.translatesAutoresizingMaskIntoConstraints = NO;

    NSTextField *title = [NSTextField labelWithString:@"UK WSR Visualizer"];
    title.font = [NSFont systemFontOfSize:30 weight:NSFontWeightSemibold];
    title.textColor = [NSColor colorWithCalibratedRed:0.10 green:0.16 blue:0.20 alpha:1.0];
    title.alignment = NSTextAlignmentCenter;
    title.translatesAutoresizingMaskIntoConstraints = NO;

    self.statusLabel = [NSTextField labelWithString:@"Starting local radar viewer..."];
    self.statusLabel.font = [NSFont systemFontOfSize:15 weight:NSFontWeightRegular];
    self.statusLabel.textColor = NSColor.secondaryLabelColor;
    self.statusLabel.alignment = NSTextAlignmentCenter;
    self.statusLabel.translatesAutoresizingMaskIntoConstraints = NO;

    NSStackView *stack = [NSStackView stackViewWithViews:@[imageView, title, self.statusLabel]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeCenterX;
    stack.spacing = 18;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.splashView addSubview:stack];

    [NSLayoutConstraint activateConstraints:@[
        [imageView.widthAnchor constraintEqualToConstant:340],
        [imageView.heightAnchor constraintEqualToConstant:340],
        [stack.centerXAnchor constraintEqualToAnchor:self.splashView.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:self.splashView.centerYAnchor]
    ]];

    NSView *container = [[NSView alloc] initWithFrame:frame];
    container.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.frame = container.bounds;
    self.splashView.frame = container.bounds;
    [container addSubview:self.webView];
    [container addSubview:self.splashView];
    self.window.contentView = container;
    [self.window makeKeyAndOrderFront:nil];
}

- (void)pollServer {
    if ([[NSDate date] timeIntervalSinceDate:self.startedAt] > self.timeoutSeconds) {
        [self.pollTimer invalidate];
        self.statusLabel.stringValue = @"The local server did not become ready. Opening the log.";
        [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:self.logPath]];
        return;
    }

    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.readyURL];
    request.timeoutInterval = 1.5;
    NSURLSessionDataTask *task = [[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        if (![http isKindOfClass:[NSHTTPURLResponse class]] || http.statusCode < 200 || http.statusCode >= 300) {
            dispatch_async(dispatch_get_main_queue(), ^{
                self.statusLabel.stringValue = @"Starting local radar viewer...";
            });
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            [self.pollTimer invalidate];
            self.statusLabel.stringValue = @"Loading radar interface...";
            NSSet *dataTypes = [WKWebsiteDataStore allWebsiteDataTypes];
            NSDate *since = [NSDate dateWithTimeIntervalSince1970:0];
            [[WKWebsiteDataStore defaultDataStore] removeDataOfTypes:dataTypes modifiedSince:since completionHandler:^{
                NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.targetURL];
                request.cachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
                [request setValue:@"no-cache" forHTTPHeaderField:@"Cache-Control"];
                [self.webView loadRequest:request];
            }];
        });
    }];
    [task resume];
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.18;
        self.splashView.animator.alphaValue = 0;
    } completionHandler:^{
        self.splashView.hidden = YES;
        self.webView.hidden = NO;
    }];
}

- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    self.statusLabel.stringValue = @"Unable to load the radar interface. Check the log.";
}

- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    self.statusLabel.stringValue = @"Unable to connect to the local radar interface. Check the log.";
}

@end

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSString *target = argc > 1 ? [NSString stringWithUTF8String:argv[1]] : @"http://127.0.0.1:8765";
        NSString *logoPath = argc > 2 ? [NSString stringWithUTF8String:argv[2]] : @"";
        NSString *logPath = argc > 3 ? [NSString stringWithUTF8String:argv[3]] : [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log"];
        NSTimeInterval timeout = argc > 4 ? atof(argv[4]) : 600;
        NSURL *url = [NSURL URLWithString:target];
        if (!url) {
            return 2;
        }
        NSApplication *app = [NSApplication sharedApplication];
        UKWSRWindowController *delegate = [[UKWSRWindowController alloc] initWithURL:url logoPath:logoPath logPath:logPath timeout:timeout];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
