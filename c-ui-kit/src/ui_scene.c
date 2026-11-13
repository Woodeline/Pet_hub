#include "ui.h"

#include <CoreText/CoreText.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

enum {
    W_SEG_L, W_SEG_R, W_SLIDER, W_SW_SHADOW, W_SW_MOTION,
    W_BTN1, W_BTN2, W_BTN3, W_FIELD, W_COUNT
};

typedef struct {
    UiRect card1, card2, card3, seg, segL, segR;
    UiRect slider, swS, swM, btn1, btn2, btn3, field;
} Layout;

struct UiState {
    int stage;
    float t;
    UiColors th;

    int theme_target;   /* 0 = light, 1 = dark */
    float theme_t;
    int shadow_on, motion_on;
    float radius;       /* 0..20 px */

    float hover[W_COUNT];
    float press[W_COUNT];
    float knob_shadow, knob_motion;

    int focus;
    int active;
    int dragging;
    float mx, my;
    int inside;
    float enter;
    int chrome;         /* 离屏出图时绘制窗口控制点，窗口宿主里为 0 */
};

static const int FOCUS_ORDER[] = {
    W_SEG_L, W_SEG_R, W_SLIDER, W_SW_SHADOW, W_SW_MOTION, W_BTN1, W_BTN2, W_FIELD
};
#define FOCUS_COUNT ((int)(sizeof FOCUS_ORDER / sizeof FOCUS_ORDER[0]))

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static float ease_out_cubic(float t) {
    float u = 1.0f - t;
    return 1.0f - u * u * u;
}

static float smoothstepf(float t) {
    return t * t * (3.0f - 2.0f * t);
}

static float approach(float cur, float target, float dt, float tau) {
    if (tau <= 0.0002f) return target;
    float k = 1.0f - expf(-dt / tau);
    return cur + (target - cur) * k;
}

static Layout get_layout(void) {
    Layout L;
    L.seg    = (UiRect){252, 22, 168, 32};
    L.segL   = (UiRect){252, 22, 84, 32};
    L.segR   = (UiRect){336, 22, 84, 32};
    L.card1  = (UiRect){20, 92, 400, 184};
    L.card2  = (UiRect){20, 292, 400, 172};
    L.card3  = (UiRect){20, 480, 400, 96};
    L.slider = (UiRect){112, 142, 190, 20};
    L.swS    = (UiRect){356, 178, 44, 26};
    L.swM    = (UiRect){356, 218, 44, 26};
    L.btn1   = (UiRect){36, 340, 96, 34};
    L.btn2   = (UiRect){142, 340, 96, 34};
    L.btn3   = (UiRect){248, 340, 96, 34};
    L.field  = (UiRect){36, 388, 368, 40};
    return L;
}

static UiRect widget_rect(Layout L, int id) {
    switch (id) {
        case W_SEG_L:     return L.segL;
        case W_SEG_R:     return L.segR;
        case W_SLIDER:    return L.slider;
        case W_SW_SHADOW: return L.swS;
        case W_SW_MOTION: return L.swM;
        case W_BTN1:      return L.btn1;
        case W_BTN2:      return L.btn2;
        case W_BTN3:      return L.btn3;
        case W_FIELD:     return L.field;
        default:          return (UiRect){0, 0, 0, 0};
    }
}

static int contains(UiRect r, float x, float y) {
    return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
}

static int widget_at(Layout L, float x, float y) {
    if (contains(L.btn3, x, y)) return -1; /* 禁用控件不接事件 */
    for (int i = 0; i < W_COUNT; i++) {
        if (i == W_BTN3) continue;
        if (contains(widget_rect(L, i), x, y)) return i;
    }
    return -1;
}

/* ---------- 颜色与形状 ---------- */

static CGColorRef make_cg(UiColor c) {
    CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGFloat comps[4] = {c.r, c.g, c.b, c.a};
    CGColorRef ref = CGColorCreate(cs, comps);
    CGColorSpaceRelease(cs);
    return ref;
}

static CGPathRef round_path(UiRect r, float radius) {
    float maxr = fminf(r.w, r.h) * 0.5f;
    if (radius > maxr) radius = maxr;
    if (radius < 0) radius = 0;
    return CGPathCreateWithRoundedRect(CGRectMake(r.x, r.y, r.w, r.h), radius, radius, NULL);
}

static void fill_round(CGContextRef ctx, UiRect r, float radius, UiColor color) {
    CGPathRef path = round_path(r, radius);
    CGColorRef cg = make_cg(color);
    CGContextAddPath(ctx, path);
    CGContextSetFillColorWithColor(ctx, cg);
    CGContextFillPath(ctx);
    CGColorRelease(cg);
    CGPathRelease(path);
}

static void stroke_round(CGContextRef ctx, UiRect r, float radius, float width, UiColor color) {
    UiRect inset = {r.x + 0.5f, r.y + 0.5f, r.w - 1.0f, r.h - 1.0f};
    CGPathRef path = round_path(inset, radius);
    CGColorRef cg = make_cg(color);
    CGContextAddPath(ctx, path);
    CGContextSetStrokeColorWithColor(ctx, cg);
    CGContextSetLineWidth(ctx, width);
    CGContextStrokePath(ctx);
    CGColorRelease(cg);
    CGPathRelease(path);
}

static void fill_circle(CGContextRef ctx, float cx, float cy, float radius, UiColor color) {
    CGColorRef cg = make_cg(color);
    CGContextSetFillColorWithColor(ctx, cg);
    CGContextFillEllipseInRect(ctx, CGRectMake(cx - radius, cy - radius, radius * 2, radius * 2));
    CGColorRelease(cg);
}

static void set_shadow(CGContextRef ctx, UiColor color, float blur, float dy) {
    CGColorRef cg = make_cg(color);
    CGContextSetShadowWithColor(ctx, CGSizeMake(0, dy), blur, cg);
    CGColorRelease(cg);
}

static void clear_shadow(CGContextRef ctx) {
    CGContextSetShadowWithColor(ctx, CGSizeZero, 0, NULL);
}

/* ---------- 文本 ---------- */

static CTLineRef build_line(float size, int medium, const char *text, UiColor color) {
    CFStringRef str = CFStringCreateWithCString(kCFAllocatorDefault, text, kCFStringEncodingUTF8);
    if (!str) return NULL;
    CTFontRef font = CTFontCreateWithName(
        medium ? CFSTR("PingFangSC-Medium") : CFSTR("PingFangSC-Regular"), size, NULL);
    CGColorRef cg = make_cg(color);
    const void *keys[] = {kCTFontAttributeName, kCTForegroundColorAttributeName};
    const void *vals[] = {font, cg};
    CFDictionaryRef attrs = CFDictionaryCreate(kCFAllocatorDefault, keys, vals, 2,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFAttributedStringRef as = CFAttributedStringCreate(kCFAllocatorDefault, str, attrs);
    CTLineRef line = CTLineCreateWithAttributedString(as);
    CFRelease(as);
    CFRelease(attrs);
    CFRelease(font);
    CGColorRelease(cg);
    CFRelease(str);
    return line;
}

static void draw_text(CGContextRef ctx, float x, float baseline, float size,
                      UiColor color, int medium, const char *text) {
    CTLineRef line = build_line(size, medium, text, color);
    if (!line) return;
    CGContextSaveGState(ctx);
    CGContextTranslateCTM(ctx, x, baseline);
    CGContextScaleCTM(ctx, 1.0f, -1.0f);
    CGContextSetTextMatrix(ctx, CGAffineTransformIdentity);
    CGContextSetTextPosition(ctx, 0, 0);
    CTLineDraw(line, ctx);
    CGContextRestoreGState(ctx);
    CFRelease(line);
}

static float text_width(float size, int medium, const char *text) {
    CTLineRef line = build_line(size, medium, text, ui_rgba(0, 0, 0, 1));
    if (!line) return 0;
    double w = CTLineGetTypographicBounds(line, NULL, NULL, NULL);
    CFRelease(line);
    return (float)w;
}

static void text_center(CGContextRef ctx, float cx, float baseline, float size,
                        UiColor color, int medium, const char *text) {
    draw_text(ctx, cx - text_width(size, medium, text) * 0.5f, baseline, size, color, medium, text);
}

static void text_right(CGContextRef ctx, float right, float baseline, float size,
                       UiColor color, int medium, const char *text) {
    draw_text(ctx, right - text_width(size, medium, text), baseline, size, color, medium, text);
}

/* ---------- 控件 ---------- */

static void draw_focus_ring(CGContextRef ctx, UiState *s, UiRect r, float radius);

static void draw_switch(CGContextRef ctx, UiState *s, UiRect r, float knob, float hover) {
    UiColors th = s->th;
    UiColor track = ui_mix(th.track, th.accent, knob);
    UiColor tint = th.dark ? ui_rgba(1, 1, 1, 1) : ui_rgba(0, 0, 0, 1);
    track = ui_mix(track, tint, 0.05f * hover);
    fill_round(ctx, r, r.h * 0.5f, track);

    float center_x = r.x + 13.0f + knob * (r.w - 26.0f);
    float center_y = r.y + r.h * 0.5f;
    if (s->shadow_on) {
        set_shadow(ctx, ui_fade(th.shadow, 0.35f * s->knob_shadow), 8.0f, 2.0f);
    }
    fill_circle(ctx, center_x, center_y, 10.0f,
                th.dark ? ui_rgba(0.88f, 0.90f, 0.96f, 1) : ui_rgba(1, 1, 1, 1));
    clear_shadow(ctx);
}

static void draw_slider(CGContextRef ctx, UiState *s, UiRect r, float value, float hover) {
    UiColors th = s->th;
    float cy = r.y + r.h * 0.5f;
    float x0 = r.x + 7.0f;
    float x1 = r.x + r.w - 7.0f;
    float kx = x0 + value * (x1 - x0);

    fill_round(ctx, (UiRect){r.x, cy - 2, r.w, 4}, 2, th.track);
    fill_round(ctx, (UiRect){r.x, cy - 2, kx - r.x, 4}, 2, th.accent);

    float kr = 7.0f + hover * 1.0f;
    if (s->shadow_on) {
        set_shadow(ctx, ui_fade(th.shadow, 0.30f * s->knob_shadow), 8.0f, 2.0f);
    }
    fill_circle(ctx, kx, cy, kr,
                th.dark ? ui_rgba(0.92f, 0.94f, 0.99f, 1) : ui_rgba(1, 1, 1, 1));
    clear_shadow(ctx);
    if (!th.dark) {
        CGColorRef ring = make_cg(th.border);
        CGContextSetStrokeColorWithColor(ctx, ring);
        CGContextSetLineWidth(ctx, 1.0f);
        CGContextStrokeEllipseInRect(ctx, CGRectMake(kx - kr, cy - kr, kr * 2, kr * 2));
        CGColorRelease(ring);
    }
}

static void draw_button(CGContextRef ctx, UiState *s, UiRect r,
                        const char *label, float hover, float press, int kind) {
    UiColors th = s->th;
    UiColor bg;
    UiColor fg;
    float radius = 10.0f;
    float scale = 1.0f - 0.03f * press;

    if (kind == 0) {
        bg = ui_mix(th.accent, th.dark ? ui_rgba(1, 1, 1, 1) : ui_rgba(0, 0, 0, 1), 0.09f * hover);
        bg = ui_mix(bg, ui_rgba(0, 0, 0, 1), 0.14f * press);
        fg = th.accent_text;
    } else if (kind == 1) {
        bg = ui_mix(th.surface_hi, th.dark ? ui_rgba(1, 1, 1, 1) : ui_rgba(0, 0, 0, 1), 0.10f * hover);
        bg = ui_mix(bg, ui_rgba(0, 0, 0, 1), 0.10f * press);
        fg = th.text;
    } else {
        bg = ui_mix(th.surface_hi, th.surface, 0.4f);
        fg = ui_fade(th.text_muted, 0.55f);
    }

    CGContextSaveGState(ctx);
    if (scale < 1.0f) {
        float cx = r.x + r.w * 0.5f;
        float cy = r.y + r.h * 0.5f;
        CGContextTranslateCTM(ctx, cx, cy);
        CGContextScaleCTM(ctx, scale, scale);
        CGContextTranslateCTM(ctx, -cx, -cy);
    }
    if (kind != 2 && s->shadow_on) {
        set_shadow(ctx, ui_fade(th.shadow, (kind == 0 ? 0.45f : 0.22f) * s->knob_shadow), 14.0f, 4.0f);
    }
    fill_round(ctx, r, radius, bg);
    clear_shadow(ctx);
    if (kind != 0) {
        stroke_round(ctx, r, radius, 1.0f, th.border);
    }
    text_center(ctx, r.x + r.w * 0.5f, r.y + r.h * 0.5f + 4.5f,
                UI_M.f_body, fg, kind == 0, label);
    CGContextRestoreGState(ctx);
}

static void draw_field(CGContextRef ctx, UiState *s, UiRect r, int focused) {
    UiColors th = s->th;
    fill_round(ctx, r, 10.0f, th.dark ? ui_mix(th.surface, th.surface_hi, 0.55f) : th.surface_hi);
    stroke_round(ctx, r, 10.0f, 1.0f, th.border);
    if (focused) draw_focus_ring(ctx, s, r, 10);
    float icon_x = r.x + 20.0f;
    float cy = r.y + r.h * 0.5f;
    CGColorRef ic = make_cg(th.text_muted);
    CGContextSetStrokeColorWithColor(ctx, ic);
    CGContextSetLineWidth(ctx, 1.6f);
    CGContextStrokeEllipseInRect(ctx, CGRectMake(icon_x - 5.5f, cy - 5.5f, 11, 11));
    CGContextMoveToPoint(ctx, icon_x + 3.5f, cy + 3.5f);
    CGContextAddLineToPoint(ctx, icon_x + 8.0f, cy + 8.0f);
    CGContextStrokePath(ctx);
    CGColorRelease(ic);

    draw_text(ctx, r.x + 40.0f, cy + 4.5f, UI_M.f_body, th.text_muted, 0, "搜索设置…");
    text_right(ctx, r.x + r.w - 14.0f, cy + 4.5f, 11, ui_fade(th.text_muted, 0.7f), 0, "⌘K");
}

static void draw_segmented(CGContextRef ctx, UiState *s, Layout L) {
    UiColors th = s->th;
    fill_round(ctx, L.seg, 10.0f, th.surface_hi);
    stroke_round(ctx, L.seg, 10.0f, 1.0f, th.border);

    float ix = L.seg.x + 3.0f + s->theme_t * 84.0f;
    UiRect ind = {ix, L.seg.y + 3.0f, 78.0f, 26.0f};
    if (s->shadow_on) {
        set_shadow(ctx, ui_fade(th.shadow, 0.30f * s->knob_shadow), 10.0f, 3.0f);
    }
    fill_round(ctx, ind, 8.0f, ui_mix(th.surface, th.text, th.dark ? 0.06f : 0.0f));
    clear_shadow(ctx);
    stroke_round(ctx, ind, 8.0f, 1.0f, th.border);

    int light_selected = s->theme_target == 0;
    text_center(ctx, L.segL.x + L.segL.w * 0.5f, L.seg.y + 21.0f, UI_M.f_body,
                light_selected ? th.text : th.text_muted, light_selected, "浅色");
    text_center(ctx, L.segR.x + L.segR.w * 0.5f, L.seg.y + 21.0f, UI_M.f_body,
                !light_selected ? th.text : th.text_muted, !light_selected, "深色");
}

static void draw_focus_ring(CGContextRef ctx, UiState *s, UiRect r, float radius) {
    UiRect o = {r.x - 3, r.y - 3, r.w + 6, r.h + 6};
    stroke_round(ctx, o, radius + 3, 2.0f, ui_fade(s->th.accent, 0.9f));
}

/* ---------- 背景与卡片 ---------- */

static void paint_background(CGContextRef ctx, float w, float h, const UiColors *th) {
    CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);

    CGColorRef cols[2] = {make_cg(th->bg_top), make_cg(th->bg_bottom)};
    CFArrayRef arr = CFArrayCreate(kCFAllocatorDefault, (const void **)cols, 2, &kCFTypeArrayCallBacks);
    CGFloat locs[2] = {0.0f, 1.0f};
    CGGradientRef g = CGGradientCreateWithColors(space, arr, locs);
    CGContextDrawLinearGradient(ctx, g, CGPointMake(0, 0), CGPointMake(0, h), 0);
    CGGradientRelease(g);
    CFRelease(arr);
    CGColorRelease(cols[0]);
    CGColorRelease(cols[1]);

    CGColorRef g1 = make_cg(ui_fade(th->accent, th->dark ? 0.13f : 0.09f));
    CGColorRef g2 = make_cg(ui_fade(th->accent, 0.0f));
    CGColorRef glows[2] = {g1, g2};
    CFArrayRef arr2 = CFArrayCreate(kCFAllocatorDefault, (const void **)glows, 2, &kCFTypeArrayCallBacks);
    CGGradientRef rg = CGGradientCreateWithColors(space, arr2, NULL);
    CGContextDrawRadialGradient(ctx, rg, CGPointMake(w * 0.5f, -60), 0,
                                CGPointMake(w * 0.5f, -60), 320, 0);
    CGGradientRelease(rg);
    CFRelease(arr2);
    CGColorRelease(g1);
    CGColorRelease(g2);

    CGColorSpaceRelease(space);
}

static float reveal(const UiState *s, float delay) {
    if (s->stage < 3) return 1.0f;
    float t = clampf((s->enter - delay) / 0.30f, 0.0f, 1.0f);
    return ease_out_cubic(t);
}

static void card_fill(CGContextRef ctx, UiState *s, UiRect r, float radius) {
    UiColors th = s->th;
    float sh = UI_M.shadow_alpha * s->knob_shadow;
    if (sh > 0.02f) {
        set_shadow(ctx, ui_fade(th.shadow, sh), UI_M.shadow_blur, UI_M.shadow_dy);
    }
    fill_round(ctx, r, radius, th.surface);
    clear_shadow(ctx);
    stroke_round(ctx, r, radius, 1.0f, th.border);
}

static void paint_header(CGContextRef ctx, UiState *s, Layout L) {
    UiColors th = s->th;
    if (s->chrome) {
        fill_circle(ctx, 30, 28, 6, ui_rgba(1.000f, 0.373f, 0.341f, 1.0f));
        fill_circle(ctx, 50, 28, 6, ui_rgba(0.996f, 0.737f, 0.180f, 1.0f));
        fill_circle(ctx, 70, 28, 6, ui_rgba(0.157f, 0.784f, 0.251f, 1.0f));
    }
    draw_text(ctx, 88, 46, UI_M.f_hero, th.text, 1, "外观设置");
    draw_text(ctx, 88, 68, UI_M.f_caption, th.text_muted, 0, "C UI Kit · 纯 C 绘制 · token 驱动");
    draw_segmented(ctx, s, L);
    if (s->focus == W_SEG_L) draw_focus_ring(ctx, s, L.segL, 10);
    if (s->focus == W_SEG_R) draw_focus_ring(ctx, s, L.segR, 10);
}

static void paint_card1(CGContextRef ctx, UiState *s, Layout L) {
    UiColors th = s->th;
    float rv = reveal(s, 0.06f);
    CGContextSaveGState(ctx);
    if (rv < 1.0f) {
        CGContextSetAlpha(ctx, rv);
        CGContextTranslateCTM(ctx, 0, (1.0f - rv) * 12.0f);
    }
    card_fill(ctx, s, L.card1, s->radius);

    draw_text(ctx, 36, 120, UI_M.f_body, th.text, 1, "主题与质感");

    draw_text(ctx, 36, 156, UI_M.f_body, th.text_muted, 0, "圆角");
    draw_slider(ctx, s, L.slider, s->radius / 20.0f, s->hover[W_SLIDER]);
    char buf[32];
    snprintf(buf, sizeof buf, "%d px", (int)lroundf(s->radius));
    text_right(ctx, 404, 156, 12, th.text_muted, 0, buf);

    draw_text(ctx, 36, 196, UI_M.f_body, th.text, 0, "投影");
    draw_switch(ctx, s, L.swS, s->knob_shadow, s->hover[W_SW_SHADOW]);
    draw_text(ctx, 36, 236, UI_M.f_body, th.text, 0, "动效");
    draw_switch(ctx, s, L.swM, s->knob_motion, s->hover[W_SW_MOTION]);
    draw_text(ctx, 36, 264, UI_M.f_caption, ui_fade(th.text_muted, 0.75f), 0,
              "圆角 / 投影 / 动效 由同一套 token 派生");

    if (s->focus == W_SLIDER) draw_focus_ring(ctx, s, L.slider, 8);
    if (s->focus == W_SW_SHADOW) draw_focus_ring(ctx, s, L.swS, 13);
    if (s->focus == W_SW_MOTION) draw_focus_ring(ctx, s, L.swM, 13);
    CGContextRestoreGState(ctx);
}static void paint_card2(CGContextRef ctx, UiState *s, Layout L) {
    UiColors th = s->th;
    float rv = reveal(s, 0.14f);
    CGContextSaveGState(ctx);
    if (rv < 1.0f) {
        CGContextSetAlpha(ctx, rv);
        CGContextTranslateCTM(ctx, 0, (1.0f - rv) * 12.0f);
    }
    card_fill(ctx, s, L.card2, s->radius);

    draw_text(ctx, 36, 320, UI_M.f_body, th.text, 1, "控件状态");
    draw_button(ctx, s, L.btn1, "主按钮", s->hover[W_BTN1], s->press[W_BTN1], 0);
    draw_button(ctx, s, L.btn2, "次按钮", s->hover[W_BTN2], s->press[W_BTN2], 1);
    draw_button(ctx, s, L.btn3, "禁用", 0, 0, 2);
    draw_field(ctx, s, L.field, s->focus == W_FIELD);
    draw_text(ctx, 36, 452, UI_M.f_caption, th.text_muted, 0, "Tab 切换焦点 · 点击 / 拖拽查看反馈");

    if (s->focus == W_BTN1) draw_focus_ring(ctx, s, L.btn1, 10);
    if (s->focus == W_BTN2) draw_focus_ring(ctx, s, L.btn2, 10);
    CGContextRestoreGState(ctx);
}

static void paint_card3(CGContextRef ctx, UiState *s, Layout L) {
    UiColors th = s->th;
    float rv = reveal(s, 0.22f);
    CGContextSaveGState(ctx);
    if (rv < 1.0f) {
        CGContextSetAlpha(ctx, rv);
        CGContextTranslateCTM(ctx, 0, (1.0f - rv) * 12.0f);
    }
    card_fill(ctx, s, L.card3, s->radius);
    draw_text(ctx, 36, 506, UI_M.f_body, th.text, 1, "对比度 · WCAG AA");

    const char *labels[3] = {"正文", "次要", "强调"};
    double ratios[3] = {
        ui_contrast(th.text, th.surface),
        ui_contrast(th.text_muted, th.surface),
        ui_contrast(th.accent_text, th.accent),
    };
    float xs[3] = {36, 160, 284};
    char buf[32];
    for (int i = 0; i < 3; i++) {
        draw_text(ctx, xs[i], 532, UI_M.f_caption, th.text_muted, 0, labels[i]);
        snprintf(buf, sizeof buf, "%.1f:1", ratios[i]);
        draw_text(ctx, xs[i], 560, UI_M.f_title, th.text, 1, buf);

        int pass = ratios[i] >= 4.5;
        float tw = text_width(UI_M.f_title, 1, buf);
        UiRect badge = {xs[i] + tw + 10.0f, 545, 32, 18};
        fill_round(ctx, badge, 9, ui_fade(th.accent, pass ? 0.16f : 0.10f));
        text_center(ctx, badge.x + badge.w * 0.5f, badge.y + 13.5f, 11,
                    pass ? th.accent : th.text_muted, 1, pass ? "AA" : "低");
    }
    CGContextRestoreGState(ctx);
}

static void paint_footer(CGContextRef ctx, UiState *s) {
    const char *cap;
    switch (s->stage) {
        case 1:  cap = "P1 · 分层表面：背景 / 卡片 / 悬浮层 · 圆角与投影"; break;
        case 2:  cap = "P2 · 控件状态：hover / pressed / focus / disabled"; break;
        case 3:  cap = "P3 · 动效：160ms 过渡 · 开关滑行中 · 入场淡入"; break;
        default: cap = "P4 · 主题：亮 / 暗 token 联动 + 对比度审计"; break;
    }
    draw_text(ctx, 20, 600, UI_M.f_caption, s->th.text_muted, 0, cap);
}

void ui_paint(CGContextRef ctx, float w, float h, UiState *s) {
    if (s->stage <= 0) {
        ui_paint_tokens(ctx, w, h, s);
        return;
    }
    float tt = smoothstepf(clampf(s->theme_t, 0.0f, 1.0f));
    s->th = ui_theme_mix(&UI_LIGHT, &UI_DARK, tt);

    paint_background(ctx, w, h, &s->th);
    Layout L = get_layout();
    paint_header(ctx, s, L);
    paint_card1(ctx, s, L);
    paint_card2(ctx, s, L);
    paint_card3(ctx, s, L);
    paint_footer(ctx, s);
}

/* ---------- P0 token 样张 ---------- */

static void hexstr(UiColor c, char *out, size_t n) {
    int r = (int)lroundf(clampf(c.r, 0, 1) * 255.0f);
    int g = (int)lroundf(clampf(c.g, 0, 1) * 255.0f);
    int b = (int)lroundf(clampf(c.b, 0, 1) * 255.0f);
    snprintf(out, n, "#%02X%02X%02X", r, g, b);
}

void ui_paint_tokens(CGContextRef ctx, float w, float h, UiState *s) {
    s->th = ui_theme_mix(&UI_LIGHT, &UI_DARK, clampf(s->theme_t, 0.0f, 1.0f));
    const UiColors *th = &s->th;
    paint_background(ctx, w, h, th);

    draw_text(ctx, 20, 46, UI_M.f_hero, th->text, 1, "P0 · 设计 token");
    draw_text(ctx, 20, 68, UI_M.f_caption, th->text_muted, 0, "ui/theme.h · 唯一事实源");

    draw_text(ctx, 20, 106, UI_M.f_caption, th->text_muted, 1, "色彩");

    struct { const char *name; UiColor c; } chips[6] = {
        {"背景", th->bg_top}, {"表面", th->surface}, {"悬浮", th->surface_hi},
        {"描边", th->border}, {"正文", th->text}, {"强调", th->accent},
    };
    char hex[16];
    for (int i = 0; i < 6; i++) {
        int col = i % 3;
        int row = i / 3;
        float x = 20.0f + col * 144.0f;
        float y = 120.0f + row * 84.0f;
        UiRect chip = {x, y, 124, 44};
        fill_round(ctx, chip, 10, chips[i].c);
        stroke_round(ctx, chip, 10, 1.0f, ui_fade(th->border, 0.9f));
        draw_text(ctx, x, y + 60, UI_M.f_caption, th->text, 0, chips[i].name);
        hexstr(chips[i].c, hex, sizeof hex);
        draw_text(ctx, x, y + 74, 11, th->text_muted, 0, hex);
    }

    draw_text(ctx, 20, 312, UI_M.f_caption, th->text_muted, 1, "间距");
    const char *sp_names[4] = {"S_1", "S_2", "S_3", "S_4"};
    int sp_vals[4] = {UI_M.s_1, UI_M.s_2, UI_M.s_3, UI_M.s_4};
    for (int i = 0; i < 4; i++) {
        float y = 326.0f + i * 22.0f;
        char label[32];
        snprintf(label, sizeof label, "%s · %d", sp_names[i], sp_vals[i]);
        draw_text(ctx, 20, y + 8, UI_M.f_caption, th->text_muted, 0, label);
        fill_round(ctx, (UiRect){100, y, (float)sp_vals[i] * 4.0f, 8}, 4, th->accent);
    }

    draw_text(ctx, 20, 432, UI_M.f_caption, th->text_muted, 1, "圆角");
    int rads[4] = {UI_M.r_xs, UI_M.r_sm, UI_M.r_md, UI_M.r_lg};
    for (int i = 0; i < 4; i++) {
        float x = 20.0f + i * 68.0f;
        fill_round(ctx, (UiRect){x, 444, 56, 36}, (float)rads[i], th->surface);
        stroke_round(ctx, (UiRect){x, 444, 56, 36}, (float)rads[i], 1.0f, th->border);
        char label[16];
        snprintf(label, sizeof label, "%d px", rads[i]);
        draw_text(ctx, x, 496, 11, th->text_muted, 0, label);
    }

    draw_text(ctx, 20, 524, UI_M.f_caption, th->text_muted, 1, "字号");
    draw_text(ctx, 20, 552, UI_M.f_caption, th->text_muted, 0, "说明 12");
    draw_text(ctx, 110, 552, UI_M.f_body, th->text, 0, "正文 13");
    draw_text(ctx, 214, 552, UI_M.f_title, th->text, 0, "标题 16");
    draw_text(ctx, 318, 552, UI_M.f_hero, th->text, 1, "大标题");

    draw_text(ctx, 20, 600, UI_M.f_caption, th->text_muted, 0,
              "P0 · 先定刻度，再谈观感");
}

/* ---------- 状态机 ---------- */

static void update_slider(UiState *s, Layout L) {
    UiRect r = L.slider;
    float x0 = r.x + 7.0f;
    float x1 = r.x + r.w - 7.0f;
    float v = clampf((s->mx - x0) / (x1 - x0), 0.0f, 1.0f);
    s->radius = roundf(v * 20.0f);
}

static void activate(UiState *s, int id) {
    switch (id) {
        case W_SEG_L:     s->theme_target = 0; break;
        case W_SEG_R:     s->theme_target = 1; break;
        case W_SW_SHADOW: s->shadow_on = !s->shadow_on; break;
        case W_SW_MOTION: s->motion_on = !s->motion_on; break;
        default: break;
    }
}

UiState *ui_create(int stage) {
    UiState *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    s->stage = stage < 0 ? 0 : (stage > 4 ? 4 : stage);
    s->focus = -1;
    s->active = -1;
    s->dragging = -1;
    s->mx = -1000;
    s->my = -1000;
    s->theme_target = 1;
    s->theme_t = 1.0f;
    s->shadow_on = 1;
    s->motion_on = 1;
    s->radius = 14.0f;
    s->knob_shadow = 1.0f;
    s->knob_motion = 1.0f;
    s->enter = 1.0f;

    if (s->stage == 4) {
        s->enter = 0.0f;
    } else if (s->stage == 2) {
        s->hover[W_SW_SHADOW] = 1.0f;
        s->hover[W_BTN2] = 1.0f;
        s->press[W_BTN1] = 0.85f;
        s->focus = W_FIELD;
    } else if (s->stage == 3) {
        Layout L = get_layout();
        float cx = L.swS.x + L.swS.w * 0.5f;
        float cy = L.swS.y + L.swS.h * 0.5f;
        ui_pointer_move(s, cx, cy);
        ui_pointer_down(s, cx, cy);
        ui_pointer_up(s, cx, cy);
        s->focus = -1;
        cx = L.btn1.x + L.btn1.w * 0.5f;
        cy = L.btn1.y + L.btn1.h * 0.5f;
        ui_pointer_move(s, cx, cy);
        ui_simulate(s, 0.085f);
        s->press[W_BTN1] = 0.0f;
    }
    return s;
}

void ui_destroy(UiState *s) {
    free(s);
}

void ui_set_theme(UiState *s, int dark) {
    s->theme_target = dark ? 1 : 0;
    s->theme_t = (float)s->theme_target;
}

void ui_set_chrome(UiState *s, int show) {
    s->chrome = show ? 1 : 0;
}

int ui_theme_is_dark(const UiState *s) {
    return s->theme_target;
}

float ui_radius_value(const UiState *s) {
    return s->radius;
}

int ui_shadow_enabled(const UiState *s) {
    return s->shadow_on;
}

int ui_focus_id(const UiState *s) {
    return s->focus;
}

void ui_tick(UiState *s, float dt) {
    if (dt <= 0) return;
    s->t += dt;
    if (s->stage >= 3) {
        s->enter = fminf(1.0f, s->enter + dt / 0.45f);
    }

    Layout L = get_layout();
    float hover_tau = (s->motion_on && s->stage >= 3) ? 0.16f : 0.0001f;
    for (int i = 0; i < W_COUNT; i++) {
        int over = 0;
        if (s->inside && i != W_BTN3 && s->stage >= 2) {
            over = contains(widget_rect(L, i), s->mx, s->my);
        }
        s->hover[i] = approach(s->hover[i], over ? 1.0f : 0.0f, dt, hover_tau);
        float target_press = (s->active == i) ? 1.0f : 0.0f;
        s->press[i] = approach(s->press[i], target_press, dt, hover_tau);
    }

    float theme_tau = (s->stage >= 4) ? 0.20f : 0.0001f;
    float theme_target = (s->stage >= 4) ? (float)s->theme_target : s->theme_t;
    s->theme_t = approach(s->theme_t, theme_target, dt, theme_tau);

    float knob_tau = (s->motion_on && s->stage >= 3) ? 0.10f : 0.0001f;
    s->knob_shadow = approach(s->knob_shadow, (float)s->shadow_on, dt, knob_tau);
    s->knob_motion = approach(s->knob_motion, (float)s->motion_on, dt, knob_tau);

    if (s->dragging >= 0) update_slider(s, L);
}

void ui_simulate(UiState *s, float seconds) {
    float dt = 1.0f / 60.0f;
    for (float t = 0; t < seconds; t += dt) {
        ui_tick(s, dt);
    }
}

void ui_pointer_move(UiState *s, float x, float y) {
    s->mx = x;
    s->my = y;
    s->inside = 1;
    if (s->dragging >= 0) update_slider(s, get_layout());
}

void ui_pointer_down(UiState *s, float x, float y) {
    Layout L = get_layout();
    s->mx = x;
    s->my = y;
    s->inside = 1;
    int id = widget_at(L, x, y);
    s->active = id;
    s->focus = id;
    if (id == W_SLIDER) {
        s->dragging = id;
        update_slider(s, L);
    }
}

void ui_pointer_up(UiState *s, float x, float y) {
    Layout L = get_layout();
    int released = widget_at(L, x, y);
    if (released >= 0 && released == s->active) {
        activate(s, released);
    }
    s->mx = x;
    s->my = y;
    s->inside = 1;
    s->active = -1;
    if (s->dragging >= 0) s->dragging = -1;
}

void ui_pointer_leave(UiState *s) {
    s->inside = 0;
    s->mx = -1000;
    s->my = -1000;
}

void ui_key(UiState *s, int key) {
    if (key == 9) { /* tab */
        int idx = -1;
        for (int i = 0; i < FOCUS_COUNT; i++) {
            if (FOCUS_ORDER[i] == s->focus) idx = i;
        }
        s->focus = FOCUS_ORDER[(idx + 1) % FOCUS_COUNT];
    } else if (key == 32) { /* space */
        activate(s, s->focus);
    } else if (key == 27) {
        s->focus = -1;
    }
}
