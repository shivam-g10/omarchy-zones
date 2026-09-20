//! Value-only geometry and drop decisions for an isolated Hyprland feasibility test.
use std::panic::{AssertUnwindSafe, catch_unwind};

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Layout {
    pub zones: [Rect; 2],
    pub valid: u32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct DropChoice {
    pub rectangle: Rect,
    pub should_snap: u32,
}

const MIN_SIZE: i32 = 32;

fn valid_rect(r: Rect) -> bool {
    r.w >= MIN_SIZE
        && r.h >= MIN_SIZE
        && r.x.checked_add(r.w).is_some()
        && r.y.checked_add(r.h).is_some()
}

fn valid_layout(layout: Layout) -> bool {
    let [left, right] = layout.zones;
    layout.valid == 1
        && valid_rect(left)
        && valid_rect(right)
        && left.y == right.y
        && left.h == right.h
        && left.x.checked_add(left.w) == Some(right.x)
}

fn split(workarea: Rect) -> Layout {
    if !valid_rect(workarea) || workarea.w < 2 * MIN_SIZE {
        return Layout::default();
    }
    let half = workarea.w / 2;
    Layout {
        zones: [
            Rect {
                w: half,
                ..workarea
            },
            Rect {
                x: workarea.x + half,
                w: workarea.w - half,
                ..workarea
            },
        ],
        valid: 1,
    }
}

fn move_boundary(layout: Layout, x: i32) -> Layout {
    if !valid_layout(layout) {
        return Layout::default();
    }
    let [left, right] = layout.zones;
    let Some(left_width) = x.checked_sub(left.x) else {
        return Layout::default();
    };
    let Some(right_width) = (right.x + right.w).checked_sub(x) else {
        return Layout::default();
    };
    if left_width < MIN_SIZE || right_width < MIN_SIZE {
        return Layout::default();
    }
    Layout {
        zones: [
            Rect {
                w: left_width,
                ..left
            },
            Rect {
                x,
                w: right_width,
                ..right
            },
        ],
        valid: 1,
    }
}

fn hit(layout: Layout, x: f64, y: f64) -> i32 {
    if !valid_layout(layout) || !x.is_finite() || !y.is_finite() {
        return -1;
    }
    for (index, r) in layout.zones.iter().enumerate() {
        if x >= f64::from(r.x)
            && x < f64::from(r.x + r.w)
            && y >= f64::from(r.y)
            && y < f64::from(r.y + r.h)
        {
            return index as i32;
        }
    }
    -1
}

fn drop_choice(layout: Layout, x: f64, y: f64, qualified: u32) -> DropChoice {
    if qualified != 1 {
        return DropChoice::default();
    }
    let index = hit(layout, x, y);
    if index < 0 {
        return DropChoice::default();
    }
    DropChoice {
        rectangle: layout.zones[index as usize],
        should_snap: 1,
    }
}

// Even an unexpected Rust panic becomes an invalid result, never an unwind into C++.
fn contain<T: Default>(operation: impl FnOnce() -> T) -> T {
    catch_unwind(AssertUnwindSafe(operation)).unwrap_or_default()
}

#[unsafe(no_mangle)]
pub extern "C" fn zones_rust_split(workarea: Rect) -> Layout {
    contain(|| split(workarea))
}

#[unsafe(no_mangle)]
pub extern "C" fn zones_rust_move_boundary(layout: Layout, x: i32) -> Layout {
    contain(|| move_boundary(layout, x))
}

#[unsafe(no_mangle)]
pub extern "C" fn zones_rust_hit(layout: Layout, x: f64, y: f64) -> i32 {
    catch_unwind(AssertUnwindSafe(|| hit(layout, x, y))).unwrap_or(-1)
}

#[unsafe(no_mangle)]
pub extern "C" fn zones_rust_drop(layout: Layout, x: f64, y: f64, qualified: u32) -> DropChoice {
    contain(|| drop_choice(layout, x, y, qualified))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn odd_workarea_is_covered_without_gap_or_overlap() {
        let layout = split(Rect {
            x: -500,
            y: 26,
            w: 1001,
            h: 700,
        });
        assert_eq!(
            layout.zones,
            [
                Rect {
                    x: -500,
                    y: 26,
                    w: 500,
                    h: 700
                },
                Rect {
                    x: 0,
                    y: 26,
                    w: 501,
                    h: 700
                }
            ]
        );
        assert!(valid_layout(layout));
        assert_eq!(hit(layout, -0.01, 26.0), 0);
        assert_eq!(hit(layout, 0.0, 26.0), 1);
        assert_eq!(hit(layout, 501.0, 26.0), -1);
        assert_eq!(hit(layout, 0.0, 726.0), -1);
    }

    #[test]
    fn invalid_extents_and_overflow_are_rejected() {
        for area in [
            Rect {
                x: 0,
                y: 0,
                w: 63,
                h: 100,
            },
            Rect {
                x: 0,
                y: 0,
                w: 100,
                h: 31,
            },
            Rect {
                x: i32::MAX,
                y: 0,
                w: 100,
                h: 100,
            },
            Rect {
                x: 0,
                y: i32::MAX,
                w: 100,
                h: 100,
            },
        ] {
            assert_eq!(split(area).valid, 0);
        }
    }

    #[test]
    fn boundary_edit_resizes_both_neighbors_and_preserves_outer_bounds() {
        let original = split(Rect {
            x: 100,
            y: 50,
            w: 1000,
            h: 800,
        });
        let changed = move_boundary(original, 450);
        assert_eq!(
            changed.zones,
            [
                Rect {
                    x: 100,
                    y: 50,
                    w: 350,
                    h: 800
                },
                Rect {
                    x: 450,
                    y: 50,
                    w: 650,
                    h: 800
                }
            ]
        );
        assert_eq!(move_boundary(original, 131).valid, 0);
        assert_eq!(move_boundary(original, 1069).valid, 0);
        assert_eq!(move_boundary(original, i32::MIN).valid, 0);
        assert_eq!(original.zones[0].w, 500);
    }

    #[test]
    fn malformed_external_layout_and_nonfinite_pointer_are_rejected() {
        let mut layout = split(Rect {
            x: 0,
            y: 0,
            w: 1000,
            h: 800,
        });
        assert_eq!(hit(layout, f64::NAN, 100.0), -1);
        assert_eq!(hit(layout, f64::INFINITY, 100.0), -1);
        layout.zones[1].x -= 1;
        assert_eq!(hit(layout, 100.0, 100.0), -1);
        assert_eq!(move_boundary(layout, 400).valid, 0);
    }

    #[test]
    fn drop_requires_explicit_activation_and_a_current_valid_target() {
        let layout = split(Rect {
            x: 0,
            y: 0,
            w: 1000,
            h: 800,
        });
        assert_eq!(drop_choice(layout, 700.0, 100.0, 0).should_snap, 0);
        assert_eq!(drop_choice(layout, 700.0, 100.0, 2).should_snap, 0);
        assert_eq!(drop_choice(layout, 1000.0, 100.0, 1).should_snap, 0);
        assert_eq!(
            drop_choice(layout, 700.0, 100.0, 1),
            DropChoice {
                rectangle: Rect {
                    x: 500,
                    y: 0,
                    w: 500,
                    h: 800
                },
                should_snap: 1
            }
        );
    }

    #[test]
    fn panic_is_contained_at_the_boundary() {
        let value: Layout = contain(|| panic!("deliberate containment test"));
        assert_eq!(value.valid, 0);
    }
}
