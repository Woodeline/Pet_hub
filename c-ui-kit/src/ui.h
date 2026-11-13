#ifndef CUI_UI_H
#define CUI_UI_H

#include <CoreGraphics/CoreGraphics.h>

#define UI_WIN_W 440.0f
#define UI_WIN_H 620.0f

typedef struct { float r, g, b, a; } UiColor;
typedef struct { float x, y, w, h; } UiRect;

typedef struct {
    UiColor bg_top, bg_bottom;
    UiColor surface, surface_hi, border;
    UiColor text, text_muted;
    UiColor accent, accent_text;
    UiColor track;
    UiColor hover;
    UiColor pressed;
    UiColor shadow;
    int dark;
} UiColors;

typedef struct {
    int r_xs, r_sm, r_md, r_lg;
    int s_1, s_2, s_3, s_4;
    int f_caption, f_body, f_title, f_hero;
    float shadow_blur;
    float shadow_dy;
    float shadow_alpha;
    float anim_ms;
    float anim_slow_ms;
} UiMetrics;

extern const UiColors UI_LIGHT;
extern const UiColors UI_DARK;
extern const UiMetrics UI_M;

UiColor ui_rgba(float r, float g, float b, float a);
UiColor ui_mix(UiColor a, UiColor b, float t);
UiColor ui_fade(UiColor c, float a);
UiColors ui_theme_mix(const UiColors *a, const UiColors *b, float t);
double ui_contrast(UiColor fg, UiColor bg);

typedef struct UiState UiState;

UiState *ui_create(int stage);
void ui_destroy(UiState *s);
void ui_tick(UiState *s, float dt);
void ui_simulate(UiState *s, float seconds);
void ui_set_theme(UiState *s, int dark);
void ui_set_chrome(UiState *s, int show);
int ui_theme_is_dark(const UiState *s);
float ui_radius_value(const UiState *s);
int ui_shadow_enabled(const UiState *s);
int ui_focus_id(const UiState *s);
void ui_pointer_move(UiState *s, float x, float y);
void ui_pointer_down(UiState *s, float x, float y);
void ui_pointer_up(UiState *s, float x, float y);
void ui_pointer_leave(UiState *s);
void ui_key(UiState *s, int key);

void ui_paint(CGContextRef ctx, float w, float h, UiState *s);
void ui_paint_tokens(CGContextRef ctx, float w, float h, UiState *s);

int ui_export_png(const char *path, int stage, int dark, float scale);
int run_demo_app(void);

#endif
