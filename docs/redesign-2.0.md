# 2.0: one interface for controller, TV and handheld

This branch carries the 2.0 interface. Tracking is on GitHub, not here:
the umbrella issue is [#56](https://github.com/4o66/sunshine-apps-ui/issues/56),
and every element and screen has its own issue on the
[2.0 milestone](https://github.com/4o66/sunshine-apps-ui/milestone/1).

## How it is being made

1. **Mockups first**, on one design canvas, drawn at every target size: the
   Legion Go S stream (1920×1200 and 1280×800), a 1080p TV, and a 1280×720
   desktop window. Real data, both themes.
2. **One element at a time.** Each is approved in its issue ("Approved
   design, <date>") before the next is drawn.
3. **Full-flow review** of every screen, in order, at every size. No interface
   code is written before it is approved.
4. **The build matches the design.** A mockup shows only what can be built as
   drawn. Where the build cannot match it exactly, work stops and the
   difference is discussed first. Each build phase ends with a design-vs-build
   comparison at the same size.

## Fixed from the start

- Mouse, keyboard and touch always work. Script adds the controller and the
  on-screen keyboard, and nothing a mouse or keyboard user needs depends on it.
- The colors are Sunshine's, as in 1.x.
- Typing is replaced by choices wherever possible. What remains uses our own
  on-screen keyboard.

## Branch

`redesign-2.0` is cut from `dev` and lives until 2.0 ships. `dev` keeps taking
1.x fixes, and they are merged forward into this branch.
