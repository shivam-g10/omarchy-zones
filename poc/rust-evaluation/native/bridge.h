#pragma once
#include <cstdint>

// The boundary contains values only: no C++ strings, owning pointers, or windows.
struct RustRect { int32_t x, y, w, h; };
struct RustLayout { RustRect zones[2]; uint32_t valid; };
struct RustDrop { RustRect rectangle; uint32_t should_snap; };

extern "C" RustLayout zones_rust_split(RustRect workarea) noexcept;
extern "C" RustLayout zones_rust_move_boundary(RustLayout layout, int32_t x) noexcept;
extern "C" int32_t zones_rust_hit(RustLayout layout, double x, double y) noexcept;
extern "C" RustDrop zones_rust_drop(RustLayout layout, double x, double y,
                                    uint32_t qualified) noexcept;
