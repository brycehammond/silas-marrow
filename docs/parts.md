# Parts list

Everything needed to build the physical skull. Wiring is in [wiring.svg](wiring.svg),
assembly is in [assembly.md](assembly.md), and print settings are in the
[README](../README.md).

Brands are the ones used in this build. Any part that matches the spec will work, but
check the printed parts against it first: the dimensions marked `(M)` in
`cad/skull_parts.scad` were measured from these exact parts. Prices and shop links are
left out because they go stale.

The on-screen skull (`python skull.py --virtual`) needs none of this, only a Mac with a
camera and a microphone.

## Electronics

| Part | Qty | Spec | Used in this build | Job |
|---|---|---|---|---|
| Arduino Uno | 1 | A Nano also works | | Drives the servos and eyes |
| Standard servo | 2 | MG996R, metal gear | Hosyond, sold as a 4-pack | Pan and tilt |
| Micro servo | 1 | MG90S, metal gear | Miuzei, sold as a 4-pack | Jaw |
| LED jewel | 2 | WS2812, 7 LEDs, 23 mm across | | Eyes |
| Power supply | 1 | 5 V, 5 A, with a barrel to screw terminal adapter | ALITOVE | Servos and eyes |
| Electrolytic capacitor | 2 | 1000 µF, rated 10 V or more | From a capacitor kit | One across the servo power rail, one across the amp's power pads |
| Resistor | 1 | 330 Ω | | In series with the eye data line |
| Amplifier board | 1 | PAM8403, with volume knob | HiLetgo | Drives the speaker |
| Speaker | 1 | 40 mm, 4 Ω | Gikfun | Voice, mounted under the jaw |
| Servo extension cable | up to 3 | One per servo that cannot reach the Arduino | | Runs from the head down into the base |
| USB wall charger | 1 | 5 V | | Powers the amp only |
| USB cable | 1 | Any spare one, to cut up | | Charger to amp |
| Audio cable | 1 | 3.5 mm, to cut up | | Headphone jack to amp |
| USB cable for the Arduino | 1 | Type B for an Uno | | Arduino to computer |
| Hookup wire | some | | | Power rail, eyes, speaker |

The 10 V rating on the capacitors is a recommendation added here. The README only gives
the capacitance.

## Computer, camera and microphone

| Part | Qty | Used in this build | Job |
|---|---|---|---|
| Computer | 1 | Mac mini | Runs `skull.py` |
| Webcam with microphone | 1 | Anker PowerConf C200, 40.8 x 50.6 x 55.1 mm with the clip folded | Sees and hears visitors |

## Mechanical

| Part | Qty | Spec | Job |
|---|---|---|---|
| Life-size plastic skull | 1 | Hinged jaw, removable cap. This build uses an Evotech skull. | Silas |
| Lazy susan bearing | 1 | Sold as 3 in. The plates measure 72 mm square, 9 mm tall, with a 35.3 mm center opening. | Carries the head on the base |
| M3 screws | about 30 | 8 to 16 mm long | Self-tap into the printed pilot holes |
| M5 bolt | 1 | 50 mm long | Idle tilt pivot |
| M5 nylon lock nut | 1 | | Idle tilt pivot |
| M5 washer | 2 | | Idle tilt pivot |
| Machine screws with nuts and washers | about 8 | Short, M3 or M4 to suit the bearing's holes | Lazy susan plates to the turntable and base. Not in the README. See the assembly guide. |
| Steel wire | 1 short length | 1.5 mm music wire, or a large paperclip | Jaw pushrod |
| Speaker grille cloth | 1 piece | Big enough to cover the camera window | Hides the camera |
| PVC pipe | 1, optional | 2 in | Stands the skull at eye level |

## Printed parts

Material, orientation and supports are in section 2 of the README.

| Part | Qty | Material |
|---|---|---|
| `base_shell` | 1 | PLA |
| `base_floor` | 1 | PLA |
| `camera_cradle` | 1 | PLA |
| `grille_frame` | 1 | PLA, black |
| `turntable` | 1 | PETG preferred |
| `horn_column` | 1 | PETG |
| `cradle` | 1 | PETG |
| `pivot_spacer` | 1 | Any |
| `speaker_holder` | 1 | PLA |
| `jaw_tab` | 2 | PLA. One is a spare. |
| `eye_holder` | 2 | PLA, black |
| `eye_diffuser` | 2 | White or translucent PLA or PETG |
| `pvc_socket` | 1, optional | PLA |

## Consumables

| Item | Job |
|---|---|
| 5-minute epoxy or E6000 | Jaw tab and eye holders |
| Double-sided foam tape | Holds the amp on its pad |
| Small zip ties | Straps the camera into its cradle |
| Raw umber acrylic paint, optional | Weathers the skull |

## Tools

| Tool | Why |
|---|---|
| 3D printer | Needs a 150 mm square bed area for `base_shell` |
| Soldering iron | The LED jewels have solder pads, and the cut audio and USB cables need joining |
| Arduino IDE | Uploads the firmware. Needs the Adafruit NeoPixel library. |

## What is left over

The servos are sold in packs of four. This build uses two MG996R and one MG90S, which
leaves two and three spare.
