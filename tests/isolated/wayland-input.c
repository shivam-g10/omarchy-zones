#define _GNU_SOURCE
// Test-only input for the explicitly selected isolated Wayland socket.
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "generated/pointer.h"
#include "generated/keyboard.h"

static struct wl_seat *seat;
static struct zwlr_virtual_pointer_manager_v1 *pointer_manager;
static struct zwp_virtual_keyboard_manager_v1 *keyboard_manager;
static uint32_t now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint32_t)(t.tv_sec * 1000 + t.tv_nsec / 1000000);
}
static void global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    (void)data; (void)version;
    if (!strcmp(interface, "wl_seat")) seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
    if (!strcmp(interface, "zwlr_virtual_pointer_manager_v1"))
        pointer_manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
    if (!strcmp(interface, "zwp_virtual_keyboard_manager_v1"))
        keyboard_manager = wl_registry_bind(registry, name, &zwp_virtual_keyboard_manager_v1_interface, 1);
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) {(void)data;(void)registry;(void)name;}
static const struct wl_registry_listener registry_listener = {global, removed};
int main(void) {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    if (!runtime || strncmp(runtime, "/tmp/ozr-", 9)) {
        fprintf(stderr, "Refusing input outside the isolated zones lab runtime\n"); return 2;
    }
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 3;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);
    if (!seat || !pointer_manager || !keyboard_manager) return 4;
    struct zwlr_virtual_pointer_v1 *pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(pointer_manager, seat);
    struct zwp_virtual_keyboard_v1 *keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(keyboard_manager, seat);
    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_rule_names names = {.layout = "us"};
    struct xkb_keymap *keymap = xkb_keymap_new_from_names(context, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
    struct xkb_state *state = xkb_state_new(keymap);
    char *keymap_text = xkb_keymap_get_as_string(keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
    size_t size = strlen(keymap_text) + 1;
    int fd = memfd_create("zones-test-keymap", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, size) || write(fd, keymap_text, size) != (ssize_t)size) return 5;
    zwp_virtual_keyboard_v1_keymap(keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, size);
    close(fd); free(keymap_text);
    wl_display_roundtrip(display);
    puts("READY"); fflush(stdout);
    char line[160], op[24]; unsigned a,b,c,d;
    while (fgets(line, sizeof line, stdin)) {
        if (sscanf(line, "%23s %u %u %u %u", op, &a, &b, &c, &d) < 1) break;
        if (!strcmp(op,"move") && sscanf(line,"%*s %u %u %u %u", &a,&b,&c,&d)==4) {
            zwlr_virtual_pointer_v1_motion_absolute(pointer, now(), a,b,c,d);
            zwlr_virtual_pointer_v1_frame(pointer);
        } else if (!strcmp(op,"button") && sscanf(line,"%*s %u %u",&a,&b)==2) {
            zwlr_virtual_pointer_v1_button(pointer, now(),a,b);
            zwlr_virtual_pointer_v1_frame(pointer);
        } else if (!strcmp(op,"key") && sscanf(line,"%*s %u %u",&a,&b)==2) {
            zwp_virtual_keyboard_v1_key(keyboard, now(),a,b);
            xkb_state_update_key(state,a+8,b?XKB_KEY_DOWN:XKB_KEY_UP);
            zwp_virtual_keyboard_v1_modifiers(keyboard,
                xkb_state_serialize_mods(state,XKB_STATE_MODS_DEPRESSED),
                xkb_state_serialize_mods(state,XKB_STATE_MODS_LATCHED),
                xkb_state_serialize_mods(state,XKB_STATE_MODS_LOCKED),
                xkb_state_serialize_layout(state,XKB_STATE_LAYOUT_EFFECTIVE));
        } else { fprintf(stderr,"Invalid test command\n"); break; }
        if (wl_display_roundtrip(display)<0) break;
        puts("OK"); fflush(stdout);
    }
    zwlr_virtual_pointer_v1_button(pointer,now(),272,0);
    zwlr_virtual_pointer_v1_frame(pointer);
    zwp_virtual_keyboard_v1_modifiers(keyboard,0,0,0,0);
    zwlr_virtual_pointer_v1_destroy(pointer);
    zwp_virtual_keyboard_v1_destroy(keyboard);
    wl_display_roundtrip(display);
    xkb_state_unref(state); xkb_keymap_unref(keymap); xkb_context_unref(context);
    wl_display_disconnect(display); return 0;
}
