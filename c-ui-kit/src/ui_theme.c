#include "ui.h"

#include <math.h>

/* P0 · 设计 token 唯一事实源：绘制代码里不出现字面量颜色/像素值 */

const UiColors UI_DARK = {
    .bg_top     = {0.071f, 0.078f, 0.102f, 1.0f}, /* #121419 */
    .bg_bottom  = {0.110f, 0.118f, 0.149f, 1.0f}, /* #1C1E26 */
    .surface    = {0.125f, 0.137f, 0.176f, 1.0f}, /* #20232D */
    .surface_hi = {0.165f, 0.180f, 0.227f, 1.0f}, /* #2A2E3A */
    .border     = {0.204f, 0.220f, 0.275f, 1.0f}, /* #343846 */
    .text       = {0.925f, 0.933f, 0.957f, 1.0f}, /* #ECEEF4 */
    .text_muted = {0.604f, 0.631f, 0.698f, 1.0f}, /* #9AA1B2 */
    .accent     = {0.424f, 0.486f, 1.000f, 1.0f}, /* #6C7CFF */
    .accent_text= {0.043f, 0.055f, 0.086f, 1.0f}, /* #0B0E16 */
    .track      = {0.200f, 0.216f, 0.275f, 1.0f}, /* #333746 */
    .hover      = {1.0f, 1.0f, 1.0f, 0.06f},
    .pressed    = {0.0f, 0.0f, 0.0f, 0.14f},
    .shadow     = {0.0f, 0.0f, 0.0f, 0.55f},
    .dark       = 1,
};

const UiColors UI_LIGHT = {
    .bg_top     = {0.965f, 0.969f, 0.984f, 1.0f}, /* #F6F7FB */
    .bg_bottom  = {0.925f, 0.937f, 0.965f, 1.0f}, /* #ECEFF6 */
    .surface    = {1.000f, 1.000f, 1.000f, 1.0f}, /* #FFFFFF */
    .surface_hi = {0.945f, 0.953f, 0.973f, 1.0f}, /* #F1F3F8 */
    .border     = {0.863f, 0.882f, 0.922f, 1.0f}, /* #DCE1EB */
    .text       = {0.082f, 0.090f, 0.118f, 1.0f}, /* #15171E */
    .text_muted = {0.361f, 0.388f, 0.451f, 1.0f}, /* #5C6373 */
    .accent     = {0.294f, 0.357f, 0.910f, 1.0f}, /* #4B5BE8 */
    .accent_text= {1.0f, 1.0f, 1.0f, 1.0f},
    .track      = {0.886f, 0.902f, 0.941f, 1.0f}, /* #E2E6F0 */
    .hover      = {0.0f, 0.0f, 0.0f, 0.035f},
    .pressed    = {0.0f, 0.0f, 0.0f, 0.07f},
    .shadow     = {0.04f, 0.06f, 0.11f, 0.30f},
    .dark       = 0,
};

const UiMetrics UI_M = {
    .r_xs = 4, .r_sm = 8, .r_md = 12, .r_lg = 16,
    .s_1 = 4, .s_2 = 8, .s_3 = 16, .s_4 = 24,
    .f_caption = 12, .f_body = 13, .f_title = 16, .f_hero = 20,
    .shadow_blur = 22.0f,
    .shadow_dy = 6.0f,
    .shadow_alpha = 0.42f,
    .anim_ms = 160.0f,
    .anim_slow_ms = 220.0f,
};

UiColor ui_rgba(float r, float g, float b, float a) {
    UiColor c = {r, g, b, a};
    return c;
}

UiColor ui_mix(UiColor a, UiColor b, float t) {
    if (t <= 0.0f) return a;
    if (t >= 1.0f) return b;
    UiColor c = {
        a.r + (b.r - a.r) * t,
        a.g + (b.g - a.g) * t,
        a.b + (b.b - a.b) * t,
        a.a + (b.a - a.a) * t,
    };
    return c;
}

UiColor ui_fade(UiColor c, float a) {
    c.a *= a;
    return c;
}

UiColors ui_theme_mix(const UiColors *a, const UiColors *b, float t) {
    UiColors o;
    o.bg_top     = ui_mix(a->bg_top, b->bg_top, t);
    o.bg_bottom  = ui_mix(a->bg_bottom, b->bg_bottom, t);
    o.surface    = ui_mix(a->surface, b->surface, t);
    o.surface_hi = ui_mix(a->surface_hi, b->surface_hi, t);
    o.border     = ui_mix(a->border, b->border, t);
    o.text       = ui_mix(a->text, b->text, t);
    o.text_muted = ui_mix(a->text_muted, b->text_muted, t);
    o.accent     = ui_mix(a->accent, b->accent, t);
    o.accent_text= ui_mix(a->accent_text, b->accent_text, t);
    o.track      = ui_mix(a->track, b->track, t);
    o.hover      = ui_mix(a->hover, b->hover, t);
    o.pressed    = ui_mix(a->pressed, b->pressed, t);
    o.shadow     = ui_mix(a->shadow, b->shadow, t);
    o.dark       = t >= 0.5f ? b->dark : a->dark;
    return o;
}

static double srgb_to_linear(double c) {
    return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4);
}

static double luminance(UiColor c) {
    return 0.2126 * srgb_to_linear(c.r)
         + 0.7152 * srgb_to_linear(c.g)
         + 0.0722 * srgb_to_linear(c.b);
}

double ui_contrast(UiColor fg, UiColor bg) {
    double l1 = luminance(fg);
    double l2 = luminance(bg);
    return l1 > l2 ? (l1 + 0.05) / (l2 + 0.05) : (l2 + 0.05) / (l1 + 0.05);
}
