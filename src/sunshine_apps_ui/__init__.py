# SPDX-License-Identifier: GPL-3.0-or-later
"""Manage the applications Sunshine offers.

A tile manager for Sunshine's apps.json, reached through Moonlight or at the
console -- both of which put the page on the host, which is why the listener
binds 127.0.0.1 and why that costs nothing.

It was two projects: this interface and bazzite-sunshine-manager, a fork of
wadiebs' importer, talking over a CLI contract. They were folded together; the
engine lives in core and still owns the file on its own. See NOTICE.
"""

from .version import display as version_display  # noqa: E402
from .version import version as _version

__version__ = _version()

# The plan document schema this version understands. Reject anything else rather
# than guessing at a shape we have not seen.
SUPPORTED_SCHEMA = 1
