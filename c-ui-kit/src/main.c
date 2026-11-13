#include "ui.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void check(int ok, const char *name, int *fails) {
    printf("%s  %s\n", ok ? "ok  " : "FAIL", name);
    if (!ok) (*fails)++;
}

static int selfcheck(void) {
    int fails = 0;
    UiState *s = ui_create(4);
    if (!s) return 1;

    ui_simulate(s, 0.6f);
    check(ui_theme_is_dark(s) == 1, "默认深色主题", &fails);

    ui_pointer_down(s, 294, 38);   /* 「浅色」段 */
    ui_pointer_up(s, 294, 38);
    ui_simulate(s, 0.6f);
    check(ui_theme_is_dark(s) == 0, "分段控件切到浅色", &fails);

    int shadow_before = ui_shadow_enabled(s);
    ui_pointer_down(s, 378, 191);  /* 投影开关 */
    ui_pointer_up(s, 378, 191);
    ui_simulate(s, 0.3f);
    check(ui_shadow_enabled(s) != shadow_before, "开关切换投影", &fails);

    ui_pointer_down(s, 207, 152);  /* 滑杆中点 */
    ui_pointer_up(s, 207, 152);
    check(fabsf(ui_radius_value(s) - 10.0f) < 0.01f, "滑杆拖到 10 px", &fails);

    ui_key(s, 9);
    int f1 = ui_focus_id(s);
    ui_key(s, 9);
    int f2 = ui_focus_id(s);
    check(f1 >= 0 && f2 >= 0 && f1 != f2, "Tab 焦点轮转", &fails);

    ui_destroy(s);
    printf("%s (%d 项失败)\n", fails ? "SELFCHECK FAILED" : "SELFCHECK PASSED", fails);
    return fails ? 1 : 0;
}

static void audit(void) {
    printf("WCAG AA audit (contrast ratio, body text needs >= 4.5:1)\n");
    printf("  dark : body %.2f:1  muted %.2f:1  accent %.2f:1\n",
           ui_contrast(UI_DARK.text, UI_DARK.surface),
           ui_contrast(UI_DARK.text_muted, UI_DARK.surface),
           ui_contrast(UI_DARK.accent_text, UI_DARK.accent));
    printf("  light: body %.2f:1  muted %.2f:1  accent %.2f:1\n",
           ui_contrast(UI_LIGHT.text, UI_LIGHT.surface),
           ui_contrast(UI_LIGHT.text_muted, UI_LIGHT.surface),
           ui_contrast(UI_LIGHT.accent_text, UI_LIGHT.accent));
}

static int parse_stage(const char *name) {
    if (!strcmp(name, "p0")) return 0;
    if (!strcmp(name, "p1")) return 1;
    if (!strcmp(name, "p2")) return 2;
    if (!strcmp(name, "p3")) return 3;
    if (!strcmp(name, "p4")) return 4;
    return -1;
}

int main(int argc, char **argv) {
    const char *render = NULL;
    const char *out = ".";
    float scale = 2.0f;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--render") && i + 1 < argc) {
            render = argv[++i];
        } else if (!strcmp(argv[i], "--out") && i + 1 < argc) {
            out = argv[++i];
        } else if (!strcmp(argv[i], "--scale") && i + 1 < argc) {
            scale = (float)atof(argv[++i]);
        } else if (!strcmp(argv[i], "--audit")) {
            audit();
            return 0;
        } else if (!strcmp(argv[i], "--selfcheck")) {
            return selfcheck();
        } else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
            printf("usage:\n"
                   "  cui                       打开交互窗口（P4 完整版）\n"
                   "  cui --render p0..p4 --out DIR [--scale 2]\n"
                   "  cui --audit               打印两套主题的 WCAG 对比度\n"
                   "  cui --selfcheck           无窗口验证交互状态机\n");
            return 0;
        }
    }

    if (!render) return run_demo_app();

    int stage = parse_stage(render);
    if (stage < 0) {
        fprintf(stderr, "unknown stage: %s (use p0..p4)\n", render);
        return 2;
    }

    char path[1024];
    if (stage == 4) {
        snprintf(path, sizeof path, "%s/p4-dark.png", out);
        if (ui_export_png(path, 4, 1, scale)) return 1;
        snprintf(path, sizeof path, "%s/p4-light.png", out);
        if (ui_export_png(path, 4, 0, scale)) return 1;
        printf("wrote %s/p4-{dark,light}.png\n", out);
    } else {
        static const char *names[] = {
            "p0-tokens", "p1-surfaces", "p2-states", "p3-motion"
        };
        snprintf(path, sizeof path, "%s/%s.png", out, names[stage]);
        if (ui_export_png(path, stage, 1, scale)) return 1;
        printf("wrote %s\n", path);
    }
    return 0;
}
