// ===========================================================================
// Talking skull: printable parts (parametric OpenSCAD)
//
// Render one part:   openscad -D 'part="turntable"' -o turntable.stl skull_parts.scad
// Preview assembly:  open this file in OpenSCAD with part="assembly"
//
// MEASURE YOUR PARTS and edit the values marked (M) before printing.
// Units: millimeters. Front of the prop is -Y (toward the people).
// ===========================================================================

part = "assembly";   // see the list at the bottom of this file
$fn = 72;
eps = 0.01;
tol = 0.3;           // general printing clearance

// ---------------- base (pedestal) ----------------
base_w = 150;  base_d = 150;  base_h = 110;
wall = 3;      top_t = 5;     corner_r = 8;
floor_t = 4;

// ---------------- lazy susan (3 in square) ----------------
ls_size = 72;      // (M) plate size
ls_h = 9;            // (M) total height of the bearing, plate to plate
ls_hole = 35.3;        // (M) diameter of the lazy susan's center opening
ls_slot_r0 = 22;     // slots along the diagonals from r0 to r1 fit most hole patterns
ls_slot_r1 = 50;

// ---------------- MG996R (neck servos) ----------------
s_L = 40;          // (M) body length
s_W = 20;          // (M) body width
s_tab_under = 32.2;  // (M) bottom of case to underside of the mounting tabs
s_tab_t = 2.4;
s_spline_top = 46.4; // (M) bottom of case to top of output spline
s_shaft_off = 10.1;  // (M) end of case to shaft center
s_hole_L = 49.2;     // (M) tab hole spacing along length
s_hole_W = 18.4;       // (M) tab hole spacing across width
s_pilot = 2.8;       // self-tapping M3 into plastic
horn_d = 20.5;         // (M) round disc horn diameter
horn_t = 2.3;          // (M) horn disc thickness above the spline

// ---------------- MG90S (jaw servo) ----------------
j_L = 22.7;  j_W = 12.2;  j_tab_under = 17.8;  j_tab_t = 2.5;
j_spline_top = 32.4;  j_shaft_off = 6.0;  j_hole_L = 30.9;  j_pilot = 1.8;

// ---------------- neck geometry ----------------
tt_d = 140;          // turntable disc diameter
tt_t = 5;
column_d = ls_hole - 4;
column_w = 17;       // the column is flattened to this width so the cables pass either side
col_screw_a = [22.5, 157.5, 202.5, 337.5];   // column screws: between the horn slots
pivot_h = 45;        // tilt axis height above the turntable top
up_t = 6;            // upright thickness
up_w = 72;           // upright width (along Y), offset to cover the servo tabs
cr_w = 70;           // cradle platform width (X)
cr_d = 84;           // cradle platform depth (Y)
cr_t = 5;
arm_t = 5;
arm_drop = 26;       // platform underside to pivot axis
horn_gap = 11;       // upright inner face to cradle arm (fits spline + horn)
pivot_bolt = 5.3;    // M5 bolt for the idle side

// ---------------- camera + window ----------------
cam_w = 40.8;          // (M) Anker C200 width
cam_h = 50.6;          // (M) height
cam_d = 55.1;          // (M) depth front to back, clip folded
cam_tilt = 12;       // degrees upward
win_w = 46;  win_h = 28;
win_z = 48;          // window center height above the bottom of the base

// ---------------- electronics ----------------
uno_holes = [[14, 2.5], [15.3, 50.7], [66.1, 7.6], [66.1, 35.5]];
pvc_od = 60.3;       // 2 in schedule 40 PVC pipe

// ===========================================================================
// helpers
// ===========================================================================
module rbox(w, d, h, r) {
    hull() for (x = [-w/2 + r, w/2 - r], y = [-d/2 + r, d/2 - r])
        translate([x, y, 0]) cylinder(r = r, h = h);
}

module slot(len, w, h) {   // along +X from origin
    hull() { cylinder(d = w, h = h); translate([len, 0, 0]) cylinder(d = w, h = h); }
}

module diag_slots(r0, r1, w, h) {
    for (a = [45, 135, 225, 315]) rotate(a) translate([r0, 0, 0]) slot(r1 - r0, w, h);
}

module horn_slots(h, angles = [0 : 45 : 315], len = 6.5) {   // radial slots that fit most disc horns
    for (a = angles) rotate(a) translate([5, 0, 0]) slot(len, 2.4, h);
}

// Footprint shared by the horn column and the middle of the turntable: a round
// column with two flats. The wires from the head run down past the flats,
// inside the lazy susan's center opening.
module column_profile(h) {
    intersection() {
        cylinder(d = column_d, h = h);
        translate([-column_d/2, -column_w/2, 0]) cube([column_d, column_w, h]);
    }
}

module cable_channels(h) {   // the two openings either side of the column
    difference() {
        cylinder(d = ls_hole, h = h);
        translate([-ls_hole/2 - 1, -column_w/2, -1]) cube([ls_hole + 2, column_w, h + 2]);
    }
}

// ===========================================================================
// 1. base shell: hollow pedestal. Print upside down (top face on the bed).
// ===========================================================================
z_hc = base_h - top_t - 2;               // horn disc top under the top plate
s_spline_z = z_hc - horn_t;
s_tab_top_z = s_spline_z - (s_spline_top - s_tab_under - s_tab_t);
s_center_x = s_L/2 - s_shaft_off;        // servo body center relative to shaft

module base_shell() {
    difference() {
        union() {
            difference() {
                rbox(base_w, base_d, base_h, corner_r);
                translate([0, 0, -eps]) rbox(base_w - 2*wall, base_d - 2*wall,
                                             base_h - top_t, corner_r - wall);
            }
            // corner bosses for the floor screws
            for (x = [-1, 1], y = [-1, 1])
                translate([x * (base_w/2 - 9), y * (base_d/2 - 9), 0])
                    cylinder(d = 11, h = 22);
            // pan servo bridges: bars under the tab holes, legs out past the horn
            for (hx = [s_center_x - s_hole_L/2, s_center_x + s_hole_L/2]) {
                translate([hx - 4, -24, s_tab_top_z]) cube([8, 48, 5]);
                for (y = [-24, 18])
                    translate([hx - 4, y, s_tab_top_z]) cube([8, 6, base_h - top_t - s_tab_top_z + eps]);
            }
        }
        // floor screw pilots
        for (x = [-1, 1], y = [-1, 1])
            translate([x * (base_w/2 - 9), y * (base_d/2 - 9), -eps]) cylinder(d = s_pilot, h = 18);
        // servo tab pilots (drilled up into the bridges)
        for (hx = [s_center_x - s_hole_L/2, s_center_x + s_hole_L/2], y = [-s_hole_W/2, s_hole_W/2])
            translate([hx, y, s_tab_top_z - eps]) cylinder(d = s_pilot, h = 5 + 2*eps);
        // clearance for the servo body between the bridges
        translate([s_center_x - s_L/2 - tol, -s_W/2 - tol, s_tab_top_z - 1])
            cube([s_L + 2*tol, s_W + 2*tol, base_h - top_t - s_tab_top_z + 1 - eps]);
        // center opening for the turntable column
        translate([0, 0, base_h - top_t - 1]) cylinder(d = column_d + 6, h = top_t + 2);
        // lazy susan screw slots
        translate([0, 0, base_h - top_t - 1]) diag_slots(ls_slot_r0, ls_slot_r1, 4.2, top_t + 2);
        // camera window + recess for the grille frame lip
        translate([-win_w/2, -base_d/2 - 1, win_z - win_h/2]) cube([win_w, wall + 2, win_h]);
        translate([-(win_w + 12)/2, -base_d/2 - 1, win_z - (win_h + 12)/2])
            cube([win_w + 12, 1 + 1.2, win_h + 12]);
        // rear cable exit
        translate([-20, base_d/2 - wall - 1, -eps]) cube([40, wall + 2, 18]);
        // side vents
        for (s = [-1, 1], i = [0 : 4])
            translate([s * base_w/2 - wall, -30 + i * 15, 60]) rotate([0, 90, 0])
                translate([0, 0, -1]) hull() { cylinder(d = 5, h = wall + 2);
                    translate([-25, 0, 0]) cylinder(d = 5, h = wall + 2); }
    }
}

// ===========================================================================
// 2. base floor: screws under the shell, carries the Arduino, amp and camera.
// ===========================================================================
uno_origin = [2, 8];    // board corner position on the floor (rear right area)

module base_floor() {
    difference() {
        union() {
            rbox(base_w, base_d, floor_t, corner_r);
            // Arduino Uno standoffs
            translate([uno_origin[0], uno_origin[1], 0])
                for (p = uno_holes) translate([p[0], p[1], 0]) cylinder(d = 6, h = floor_t + 6);
            // amp mounting pad (stick the PAM8403 on with foam tape)
            translate([-60, 25, 0]) cube([36, 28, floor_t + 2]);
        }
        for (x = [-1, 1], y = [-1, 1])
            translate([x * (base_w/2 - 9), y * (base_d/2 - 9), -eps]) {
                cylinder(d = 3.4, h = floor_t + 1);
                cylinder(d1 = 7, d2 = 3.4, h = 2);   // countersink
            }
        translate([uno_origin[0], uno_origin[1], 0])
            for (p = uno_holes) translate([p[0], p[1], 1]) cylinder(d = 2.5, h = 20);
        // camera cradle screw holes
        for (x = [-20, 20]) translate([x, -base_d/2 + wall + 22, -eps]) {
            cylinder(d = 3.4, h = floor_t + 1);
            cylinder(d1 = 7, d2 = 3.4, h = 2);
        }
        // PVC socket screw holes
        for (a = [0 : 90 : 270]) rotate(a + 45) translate([pvc_od/2 + 8, 0, -eps]) cylinder(d = 3.4, h = floor_t + 1);
        // cable pass-through to a pedestal pipe
        translate([0, 0, -eps]) cylinder(d = 26, h = floor_t + 1);
    }
}

// ===========================================================================
// 3. camera cradle: holds the Anker behind the window, tilted up.
// ===========================================================================
module camera_cradle() {
    shelf_z = win_z - floor_t - cam_h/2;          // height of the shelf front edge
    difference() {
        union() {
            // feet
            translate([-30, 0, 0]) cube([60, 14, 4]);
            // tilted shelf with back stop and front lip
            translate([0, 2, shelf_z]) rotate([cam_tilt, 0, 0]) {
                translate([-cam_w/2 - 3, 0, -3]) cube([cam_w + 6, cam_d + 3, 3]);
                translate([-cam_w/2 - 3, cam_d + tol, 0]) cube([cam_w + 6, 3, cam_h * 0.6]);
                translate([-cam_w/2 - 3, -2, 0]) cube([cam_w + 6, 2, 2.5]);
            }
            // legs
            for (x = [-24, 24]) hull() {
                translate([x - 3, 0, 0]) cube([6, 14, 4]);
                translate([0, 2, shelf_z]) rotate([cam_tilt, 0, 0])
                    translate([x - 3, 2, -3]) cube([6, cam_d - 4, 1]);
            }
        }
        for (x = [-20, 20]) translate([x, 7, -eps]) cylinder(d = 2.8, h = 10);
        // zip tie slots through the shelf
        translate([0, 2, shelf_z]) rotate([cam_tilt, 0, 0])
            for (x = [-cam_w/2 + 8, cam_w/2 - 8]) translate([x - 2.5, cam_d/2 - 5, -5]) cube([5, 3.5, 8]);
    }
}

// ===========================================================================
// 4. grille frame: clamps speaker cloth over the camera window.
// ===========================================================================
module grille_frame() {   // origin: window center on the outer wall face
    cloth = 0.4;
    pw = win_w - 2*cloth - tol;  ph = win_h - 2*cloth - tol;
    difference() {
        union() {
            translate([-(win_w + 11)/2, 0, -(win_h + 11)/2]) cube([win_w + 11, 1.2, win_h + 11]);
            translate([-pw/2, 1.2 - eps, -ph/2]) cube([pw, wall - 0.4, ph]);
        }
        translate([-(win_w - 6)/2, -1, -(win_h - 6)/2]) cube([win_w - 6, 10, win_h - 6]);
    }
}

// ===========================================================================
// 5. turntable: sits on the lazy susan, driven by the pan servo horn below,
//    carries the tilt yoke (servo side at +X, bolt side at -X).
// ===========================================================================
up_x = cr_w/2 + horn_gap + up_t/2;        // upright center X
col_len = ls_h + top_t + 2;               // turntable underside down to the horn

module servo_cutout_side(thick) {
    // MG996R case-top passes through a plate lying in the YZ plane,
    // shaft on the plate's local origin, servo length along Y.
    cy = s_center_x;
    translate([-1, cy - s_L/2 - tol, -s_W/2 - tol]) cube([thick + 2, s_L + 2*tol, s_W + 2*tol]);
    for (y = [cy - s_hole_L/2, cy + s_hole_L/2], z = [-s_hole_W/2, s_hole_W/2])
        translate([-1, y, z]) rotate([0, 90, 0]) cylinder(d = s_pilot, h = thick + 2);
}

module turntable() {
    difference() {
        union() {
            cylinder(d = tt_d, h = tt_t);
            // uprights
            for (s = [-1, 1]) translate([s * up_x - up_t/2, s_center_x - up_w/2, 0])
                cube([up_t, up_w, pivot_h + 22]);
            // gussets
            for (s = [-1, 1], y = [s_center_x - up_w/2, s_center_x + up_w/2 - 4])
                hull() {
                    translate([s * up_x - up_t/2, y, 0]) cube([up_t, 4, pivot_h - 8]);
                    translate([s * (up_x - 14) - up_t/2, y, 0]) cube([up_t, 4, 1]);
                }
        }
        // screwdriver hole for the horn screw + countersunk screws for the column
        translate([0, 0, -1]) cylinder(d = 6, h = tt_t + 2);
        for (a = col_screw_a) rotate(a) translate([9.5, 0, -1]) {
            cylinder(d = 3.4, h = tt_t + 2);
            translate([0, 0, tt_t + 1 - 2]) cylinder(d1 = 3.4, d2 = 7, h = 2 + eps);
        }
        // lazy susan top plate slots
        translate([0, 0, -eps]) diag_slots(ls_slot_r0 + 4, ls_slot_r1, 4.2, tt_t + 1);
        // tilt servo cutout in the +X upright (servo body sits outside)
        translate([up_x - up_t/2, 0, tt_t + pivot_h]) servo_cutout_side(up_t);
        // pivot bolt hole in the -X upright
        translate([-up_x - up_t/2 - 1, 0, tt_t + pivot_h]) rotate([0, 90, 0]) cylinder(d = pivot_bolt, h = up_t + 2);
        // cable openings, in line with the flats of the horn column
        translate([0, 0, -eps]) cable_channels(tt_t + 1);
    }
}

// horn column: screws under the turntable, reaches down through the lazy
// susan to the pan servo's disc horn. Screw the horn on BEFORE fitting the servo.
// Its sides are flat so the wires can pass. Trim the disc horn to the same
// width (column_w), or it will block the way down.
module horn_column() {
    difference() {
        column_profile(col_len);
        // full slots along the column, short ones on the diagonals so the flats stay solid
        translate([0, 0, -eps]) horn_slots(8, [0, 180]);
        translate([0, 0, -eps]) horn_slots(8, [45, 135, 225, 315], 3.6);
        translate([0, 0, -eps]) cylinder(d = 9, h = 3);           // spline hub clearance
        translate([0, 0, -1]) cylinder(d = 6, h = col_len + 2);    // screwdriver access
        // pilots stop above the horn slots
        for (a = col_screw_a) rotate(a) translate([9.5, 0, col_len - 7]) cylinder(d = s_pilot, h = 8);
    }
}

// spacer for the idle pivot bolt between the -X upright and the cradle arm
module pivot_spacer() {
    difference() { cylinder(d = 12, h = horn_gap - 0.5); translate([0, 0, -1]) cylinder(d = pivot_bolt + 0.2, h = horn_gap + 2); }
}

// ===========================================================================
// 6. skull cradle: platform the skull sits on, hung from the tilt axis.
//    Origin = tilt axis. Long Y slots let you slide the skull to balance it.
// ===========================================================================
module cradle() {
    plat_z = arm_drop;
    difference() {
        union() {
            translate([-cr_w/2, -cr_d/2, plat_z]) cube([cr_w, cr_d, cr_t]);
            for (s = [-1, 1]) hull() {
                translate([s * (cr_w/2 - arm_t/2) - arm_t/2, -22, plat_z]) cube([arm_t, 44, cr_t]);
                translate([s * (cr_w/2 - arm_t/2) - arm_t/2, 0, 0]) rotate([0, 90, 0]) cylinder(r = 15, h = arm_t);
            }
            // jaw servo plate hanging under the front edge (YZ plane)
            translate([10, -cr_d/2, plat_z - 36]) cube([4, 34, 36 + eps]);
            translate([10, -cr_d/2, plat_z - 4]) cube([14, 34, 4 + eps]);
        }
        // balance slots for screws into the skull base
        for (x = [-22, 22]) translate([x, -24, plat_z - 1]) rotate(90) slot(48, 4.2, cr_t + 2);
        // big cable hole under the foramen magnum
        translate([0, 6, plat_z - 1]) cylinder(d = 30, h = cr_t + 2);
        // horn hub on the +X arm, bolt hole on the -X arm
        translate([cr_w/2 - arm_t - 1, 0, 0]) rotate([0, 90, 0]) { horn_slots(arm_t + 2); cylinder(d = 9, h = arm_t + 2); }
        translate([-cr_w/2 - 1, 0, 0]) rotate([0, 90, 0]) cylinder(d = pivot_bolt, h = arm_t + 2);
        // MG90S in the jaw plate: shaft forward and low
        translate([9, -cr_d/2 + 5 + j_L/2, plat_z - 22]) {   // body center; shaft at the front end
            translate([0, -j_L/2 - tol, -j_W/2 - tol]) cube([6, j_L + 2*tol, j_W + 2*tol]);
            for (y = [-j_hole_L/2, j_hole_L/2]) translate([0, y, 0]) rotate([0, 90, 0]) cylinder(d = j_pilot, h = 6);
        }
        // speaker holder screw holes in the front edge
        for (x = [-26, -6]) translate([x, -cr_d/2 - 1, plat_z + cr_t/2]) rotate([-90, 0, 0]) cylinder(d = 2.8, h = 10);
    }
}

// ===========================================================================
// 7. speaker holder: 40 mm speaker facing forward under the jaw.
// ===========================================================================
spk_d = 39.8;   // (M)
module speaker_holder() {   // print ring-down; mount with the ear up
    difference() {
        union() {
            cylinder(d = spk_d + 6, h = 8);
            translate([-16, -(spk_d/2 + 22), 4]) cube([32, 22, 4]);
        }
        translate([0, 0, 1.5]) cylinder(d = spk_d + tol, h = 10);          // speaker pocket
        translate([0, 0, -1]) cylinder(d = spk_d - 5, h = 4);              // sound opening (front)
        for (x = [-10, 10]) translate([x, -(spk_d/2 + 16), 0]) cylinder(d = 3.2, h = 10);
        for (a = [30, 150, 270]) rotate(a) translate([spk_d/2 + 0.5, -2, 3]) cube([4, 4, 10]);  // zip tie
    }
}

// ===========================================================================
// 8. jaw tab: glue to the inside of the chin; the pushrod Z-bend hooks in.
// ===========================================================================
module jaw_tab() {
    difference() {
        union() {
            translate([-8, -6, 0]) cube([16, 12, 2]);
            translate([-1.75, -6, 0]) cube([3.5, 12, 9]);
        }
        for (z = [4.5, 7]) translate([-3, 0, z]) rotate([0, 90, 0]) cylinder(d = 1.8, h = 6);
        // glue grooves
        for (y = [-4, 0, 4]) translate([-9, y - 0.5, -eps]) cube([18, 1, 0.6]);
    }
}

// ===========================================================================
// 9. eye holder + diffuser: 7-LED jewel behind a frosted dome in each socket.
// ===========================================================================
jewel_d = 22.9;   // (M)
module eye_holder() {
    difference() {
        cylinder(d = jewel_d + 5, h = 6);
        translate([0, 0, 1.6]) cylinder(d = jewel_d + tol, h = 6);
        translate([-4, -2, -eps]) cube([8, 4, 3]);                          // wires out the back
        translate([0, 0, 5]) difference() { cylinder(d = jewel_d + 6, h = 2); cylinder(d = jewel_d + 2.2, h = 2); }
    }
}
module eye_diffuser() {   // print in translucent or white PLA/PETG, 2 perimeters
    difference() {
        union() {
            scale([1, 1, 0.45]) sphere(d = jewel_d + 8);
            translate([0, 0, -1.5]) cylinder(d = jewel_d + 2, h = 1.5 + eps);
        }
        scale([1, 1, 0.45]) sphere(d = jewel_d + 6.4);
        translate([0, 0, -50]) cube(100, center = true);
        translate([0, 0, -2]) cylinder(d = jewel_d + 0.4, h = 2 + eps);
    }
}

// ===========================================================================
// 10. PVC socket: optional, puts the base on a 2 in PVC pipe column.
// ===========================================================================
module pvc_socket() {
    difference() {
        union() {
            cylinder(d = pvc_od + 30, h = 4);
            cylinder(d = pvc_od + 8, h = 40);
        }
        translate([0, 0, -eps]) cylinder(d = 24, h = 5);
        translate([0, 0, 4]) cylinder(d = pvc_od + 0.6, h = 40);
        for (a = [0 : 90 : 270]) rotate(a + 45) translate([pvc_od/2 + 8, 0, -eps]) cylinder(d = 2.8, h = 10);
        translate([pvc_od/2, 0, 25]) rotate([0, 90, 0]) cylinder(d = 3.4, h = 10);  // set screw
    }
}

// ===========================================================================
// assembly preview (not for printing)
// ===========================================================================
module assembly(tilt = 0) {
    color("#5a4636") base_shell();
    color("#3b2f25") translate([0, 0, -floor_t]) base_floor();
    color("#777") translate([0, -base_d/2 + wall + 15, 0]) camera_cradle();
    color("#222") translate([0, -base_d/2, win_z]) grille_frame();
    color("silver", 0.6) translate([-ls_size/2, -ls_size/2, base_h]) difference() {
        cube([ls_size, ls_size, ls_h]); translate([ls_size/2, ls_size/2, -1]) cylinder(d = ls_hole, h = ls_h + 2); }
    translate([0, 0, base_h + ls_h]) {
        color("#8a6d52") turntable();
        color("#6d563f") translate([0, 0, -col_len]) horn_column();
        translate([0, 0, tt_t + pivot_h]) rotate([tilt, 0, 0]) {
            color("#a88a6a") cradle();
            color("#2d2d2d") translate([-16, -cr_d/2 - 8, arm_drop + cr_t/2 - (spk_d/2 + 16)]) rotate([-90, 0, 0]) speaker_holder();
            color("ivory", 0.35) translate([0, 10, arm_drop + cr_t + 62]) scale([0.72, 0.95, 0.75]) sphere(d = 190);   // stand-in for the skull
        }
    }
}

// ===========================================================================
if (part == "assembly") assembly();
else if (part == "assembly_tilted") assembly(15);
else if (part == "base_shell") translate([0, 0, base_h]) rotate([180, 0, 0]) base_shell();   // top on the bed
else if (part == "base_floor") base_floor();
else if (part == "camera_cradle") camera_cradle();
else if (part == "grille_frame") rotate([90, 0, 0]) grille_frame();
else if (part == "turntable") turntable();
else if (part == "cradle") translate([0, 0, arm_drop + cr_t]) rotate([180, 0, 0]) cradle();   // platform on the bed
else if (part == "horn_column") horn_column();
else if (part == "pivot_spacer") pivot_spacer();
else if (part == "speaker_holder") speaker_holder();
else if (part == "jaw_tab") jaw_tab();
else if (part == "eye_holder") eye_holder();
else if (part == "eye_diffuser") eye_diffuser();
else if (part == "pvc_socket") pvc_socket();
