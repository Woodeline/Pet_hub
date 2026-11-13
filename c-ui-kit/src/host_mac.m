#import <Cocoa/Cocoa.h>

#include "ui.h"

@interface CanvasView : NSView
@property (nonatomic, assign) UiState *state;
@end

@implementation CanvasView {
    NSTimer *_timer;
}

- (BOOL)isFlipped { return YES; }
- (BOOL)acceptsFirstResponder { return YES; }
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }

- (void)viewDidMoveToWindow {
    [super viewDidMoveToWindow];
    if (!self.window || _timer) return;
    [self.window makeFirstResponder:self];
    __weak CanvasView *weakSelf = self;
    _timer = [NSTimer scheduledTimerWithTimeInterval:1.0 / 60.0 repeats:YES block:^(NSTimer *timer) {
        CanvasView *view = weakSelf;
        if (!view) return;
        ui_tick(view.state, 1.0f / 60.0f);
        [view setNeedsDisplay:YES];
    }];
    _timer.tolerance = 0.004;
}

- (void)updateTrackingAreas {
    [super updateTrackingAreas];
    for (NSTrackingArea *area in self.trackingAreas) {
        [self removeTrackingArea:area];
    }
    NSTrackingArea *area = [[NSTrackingArea alloc]
        initWithRect:NSZeroRect
             options:(NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited |
                      NSTrackingActiveInKeyWindow | NSTrackingInVisibleRect)
               owner:self
            userInfo:nil];
    [self addTrackingArea:area];
}

- (NSPoint)localPoint:(NSEvent *)event {
    return [self convertPoint:event.locationInWindow fromView:nil];
}

- (void)mouseMoved:(NSEvent *)event {
    NSPoint p = [self localPoint:event];
    ui_pointer_move(self.state, (float)p.x, (float)p.y);
}

- (void)mouseEntered:(NSEvent *)event {
    NSPoint p = [self localPoint:event];
    ui_pointer_move(self.state, (float)p.x, (float)p.y);
}

- (void)mouseExited:(NSEvent *)event {
    ui_pointer_leave(self.state);
}

- (void)mouseDown:(NSEvent *)event {
    NSPoint p = [self localPoint:event];
    ui_pointer_down(self.state, (float)p.x, (float)p.y);
}

- (void)mouseDragged:(NSEvent *)event {
    NSPoint p = [self localPoint:event];
    ui_pointer_move(self.state, (float)p.x, (float)p.y);
}

- (void)mouseUp:(NSEvent *)event {
    NSPoint p = [self localPoint:event];
    ui_pointer_up(self.state, (float)p.x, (float)p.y);
}

- (void)keyDown:(NSEvent *)event {
    NSString *chars = event.charactersIgnoringModifiers;
    unichar c = chars.length ? [chars characterAtIndex:0] : 0;
    if (c == '\t') {
        ui_key(self.state, 9);
        return;
    }
    if (c == ' ') {
        ui_key(self.state, 32);
        return;
    }
    if (c == 27) {
        ui_key(self.state, 27);
        return;
    }
    [super keyDown:event];
}

- (void)drawRect:(NSRect)dirtyRect {
    CGContextRef ctx = [[NSGraphicsContext currentContext] CGContext];
    ui_paint(ctx, (float)self.bounds.size.width, (float)self.bounds.size.height, self.state);
}

@end

@interface AppDelegate : NSObject <NSApplicationDelegate>
@end

@implementation AppDelegate {
    NSWindow *_window;
    UiState *_state;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    _state = ui_create(4);

    NSRect rect = NSMakeRect(0, 0, UI_WIN_W, UI_WIN_H);
    NSWindowStyleMask mask = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                             NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskFullSizeContentView;
    _window = [[NSWindow alloc] initWithContentRect:rect styleMask:mask
                                            backing:NSBackingStoreBuffered defer:NO];
    _window.title = @"C UI Kit";
    _window.titleVisibility = NSWindowTitleHidden;
    _window.titlebarAppearsTransparent = YES;
    _window.movableByWindowBackground = YES;
    _window.backgroundColor = [NSColor colorWithSRGBRed:0.071 green:0.078 blue:0.102 alpha:1.0];

    CanvasView *view = [[CanvasView alloc] initWithFrame:rect];
    view.state = _state;
    _window.contentView = view;

    [_window center];
    [_window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

@end

int run_demo_app(void) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];

        NSMenu *menubar = [[NSMenu alloc] init];
        NSMenuItem *appItem = [[NSMenuItem alloc] init];
        [menubar addItem:appItem];
        NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"C UI Kit"];
        [appMenu addItemWithTitle:@"退出 C UI Kit" action:@selector(terminate:) keyEquivalent:@"q"];
        appItem.submenu = appMenu;
        app.mainMenu = menubar;

        AppDelegate *delegate = [[AppDelegate alloc] init];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
