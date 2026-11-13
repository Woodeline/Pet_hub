#include "ui.h"

#include <CoreFoundation/CoreFoundation.h>
#include <ImageIO/ImageIO.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int ui_export_png(const char *path, int stage, int dark, float scale) {
    if (scale < 0.25f) scale = 1.0f;
    int W = (int)lroundf(UI_WIN_W * scale);
    int H = (int)lroundf(UI_WIN_H * scale);
    size_t stride = (size_t)W * 4;
    uint8_t *pixels = calloc((size_t)H, stride);
    if (!pixels) return 1;

    CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef ctx = CGBitmapContextCreate(pixels, W, H, 8, stride, space,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(space);
    if (!ctx) {
        free(pixels);
        return 1;
    }

    /* 逻辑坐标 440×620、y 向下；离屏按 scale 放大（等同 Retina 2x） */
    CGContextScaleCTM(ctx, scale, -scale);
    CGContextTranslateCTM(ctx, 0, -UI_WIN_H);

    UiState *s = ui_create(stage);
    if (!s) {
        CGContextRelease(ctx);
        free(pixels);
        return 1;
    }
    ui_set_theme(s, dark);
    if (stage >= 1) ui_set_chrome(s, 1); /* 静态出图模拟窗口控制点 */
    if (stage >= 4) {
        ui_pointer_leave(s);
        ui_simulate(s, 0.7f);
    }
    ui_paint(ctx, UI_WIN_W, UI_WIN_H, s);
    ui_destroy(s);

    CGImageRef image = CGBitmapContextCreateImage(ctx);
    CGContextRelease(ctx);
    if (!image) {
        free(pixels);
        return 1;
    }

    int rc = 1;
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(
        kCFAllocatorDefault, (const UInt8 *)path, (CFIndex)strlen(path), false);
    if (url) {
        CGImageDestinationRef dst = CGImageDestinationCreateWithURL(url, CFSTR("public.png"), 1, NULL);
        if (dst) {
            CGImageDestinationAddImage(dst, image, NULL);
            rc = CGImageDestinationFinalize(dst) ? 0 : 1;
            CFRelease(dst);
        }
        CFRelease(url);
    }

    CGImageRelease(image);
    free(pixels);
    return rc;
}
