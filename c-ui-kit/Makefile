CC      ?= clang
CFLAGS  ?= -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter
LDFLAGS  = -framework Cocoa -framework CoreGraphics -framework CoreText \
           -framework ImageIO -framework CoreFoundation

BUILD = build
BIN   = $(BUILD)/cui
OBJ   = $(BUILD)/ui_theme.o $(BUILD)/ui_scene.o $(BUILD)/ui_export.o \
        $(BUILD)/main.o $(BUILD)/host_mac.o

all: $(BIN)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.o: src/%.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/host_mac.o: src/host_mac.m | $(BUILD)
	$(CC) -fobjc-arc -O2 -Wall -c $< -o $@

$(BIN): $(OBJ)
	$(CC) $(OBJ) $(LDFLAGS) -o $@

shots: $(BIN)
	mkdir -p $(BUILD)/shots
	$(BIN) --render p0 --out $(BUILD)/shots
	$(BIN) --render p1 --out $(BUILD)/shots
	$(BIN) --render p2 --out $(BUILD)/shots
	$(BIN) --render p3 --out $(BUILD)/shots
	$(BIN) --render p4 --out $(BUILD)/shots
	$(BIN) --audit

run: $(BIN)
	$(BIN)

clean:
	rm -rf $(BUILD)

.PHONY: all shots run clean
