# Light Bench icon

## Web page — put in <head>
```html
<link rel="icon" href="/favicon.ico" sizes="any">             <!-- 16–256, all browsers -->
<link rel="icon" href="/favicon.svg" type="image/svg+xml">    <!-- crisp tab icon in Chrome/Firefox/Edge -->
<link rel="apple-touch-icon" href="/apple-touch-icon.png">    <!-- 180px -->
```
`favicon.ico` holds 16, 20, 24, 32, 40, 48, 64, 128 and 256 px. The 16–40 px sizes are
simplified drawings (just the bulb and bench) so they stay readable in a browser tab, and 48 px and up use the full design.
`favicon.svg` is the simplified drawing too, because browsers draw it at tab size.
`icon-192.png` and `lightbench-512.png` are for a web app manifest if you add one.

## Python / Tkinter
```python
import sys, tkinter as tk
root = tk.Tk()
if sys.platform == "win32":
    root.iconbitmap(default="favicon.ico")          # title bar + taskbar, uses all sizes
else:                                                # Linux/macOS: .ico is not supported
    imgs = [tk.PhotoImage(file=f"lightbench-{s}.png") for s in (16, 32, 48, 64, 128)]
    root.iconphoto(True, *imgs)                      # keep `imgs` referenced
```
(PhotoImage reads PNG natively in Tk 8.6+.)

## Sources
- `src/master.svg` — full design (bulb, wrench, hammer, bench), 48 px and up
- `src/small32.svg` — simplified, 24–40 px
- `src/small16.svg` — pixel-tuned, 16–20 px
