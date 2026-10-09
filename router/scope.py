"""Channel scope: which capabilities each channel is allowed to ask for.

This is the policy layer that sits in front of the router. The router receives
the resulting list as ``reachable_caps`` and treats it as the outer boundary for
everything the planner may do.
"""

from __future__ import annotations

from router.models import Channel

_READ_ONLY = {"diagnose_voicemail", "check_service_status", "answer_question", "safe_reply"}

CHANNEL_CAPS: dict[Channel, list[str]] = {
    Channel.CHAT: sorted(_READ_ONLY),
    Channel.SLACK: sorted(_READ_ONLY),
    # Only the admin channel may reach the mutating capability.
    Channel.ADMIN: sorted(_READ_ONLY | {"apply_voicemail_fix"}),
}


def reachable_for(channel: Channel) -> list[str]:
    return list(CHANNEL_CAPS.get(channel, []))
