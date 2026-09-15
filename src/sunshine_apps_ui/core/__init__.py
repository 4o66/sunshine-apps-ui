# SPDX-License-Identifier: GPL-3.0-or-later
"""The engine: everything that reads and writes Sunshine's apps.json.

This was a separate project (bazzite-sunshine-manager, a fork of wadiebs'
work) talking to the interface over a CLI contract. The contract kept two
projects honest about their boundary, which was worth having while there
were two; with one it only bought a subprocess per request and two of
everything else. The boundary survives as a package rather than a process:
nothing outside core writes apps.json.

Derived from MIT-licensed work. See NOTICE.
"""
