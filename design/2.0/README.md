# 2.0 design prototypes

Each `.html` here is one screen of the proposed 2.0 interface, written with
`app.css`, the stylesheet 2.0 will ship. They are what the boards on the design
canvas are captured from, so they are the spec: the build matches them, and
where it cannot, that is raised before going on (#56).

**How the boards are made.** A small server serves this folder the way the
app's server serves pages: `app.css` is put inline, the same
Content-Security-Policy is sent, and `?theme=` and `?scale=couch|desk` set what
the real server sets. The page is opened in our own window, fullscreen, on a
Bazzite test machine switched to each target size (1920×1200, 1280×800,
1920×1080, and 1280×720 at the machine), and the frame is captured.

**Not in git:** `img/` (game covers and cached SteamGridDB pictures, copied
from a test machine for realistic data; they are other people's artwork) and
`shots/` (the captures). Both are ignored.

Only `foundations.html` has anything a real page would not: it shows several
controls focused at once, with exactly the focus rule `app.css` gives.
