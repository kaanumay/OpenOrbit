"""Read-only player and Dispatch diagnostics for the in-game GM Center.

The game server remains the source of truth.  This module deliberately keeps
snapshot construction separate from mutations so the overlay can refresh
without touching live gameplay state.
"""
from __future__ import annotations

import time


def gate_status(*, built, completed, wave, sent_until=None, now=None):
    """Describe the Dispatch eligibility of one gate.

    This mirrors Dispatch.send_gate()'s current rules rather than guessing from
    the client-side list: built, first wave, manually completed at least once,
    and not already dispatched.
    """
    now = time.time() if now is None else float(now)

    if sent_until is not None:
        remaining = max(0, int(float(sent_until) - now))
        if remaining:
            return {
                "status": "dispatching",
                "can_send": False,
                "can_collect": False,
                "time_left": remaining,
                "reason": "Wrota są już wysłane do Dispatch.",
            }
        return {
            "status": "ready_to_collect",
            "can_send": False,
            "can_collect": True,
            "time_left": 0,
            "reason": "Nagroda z wrót jest gotowa do odebrania.",
        }

    if not built:
        return {
            "status": "building",
            "can_send": False,
            "can_collect": False,
            "time_left": 0,
            "reason": "Brakuje części do zbudowania wrót.",
        }
    if int(wave or 0) != 0:
        return {
            "status": "gate_in_progress",
            "can_send": False,
            "can_collect": False,
            "time_left": 0,
            "reason": "Wrota są już rozpoczęte; Dispatch wymaga pierwszej fali.",
        }
    if not completed:
        return {
            "status": "first_manual_completion_required",
            "can_send": False,
            "can_collect": False,
            "time_left": 0,
            "reason": "Wrota muszą zostać ukończone ręcznie co najmniej raz.",
        }
    return {
        "status": "ready_to_send",
        "can_send": True,
        "can_collect": False,
        "time_left": 0,
        "reason": "Wrota spełniają warunki wysyłki.",
    }


def player_snapshot(person):
    """Compact, UI-oriented view of a topluluk.Kisi."""
    profile = person.profil
    with profile.lock:
        data = profile.d
        pilot = data.get("pilot") or {}
        ship = data.get("gemi") or {}
        location = data.get("konum") or {}
        return {
            "uid": str(profile.user_id),
            "name": str(pilot.get("userName") or "Unknown"),
            "online": person.oturum is not None,
            "map_id": location.get("mapId"),
            "level": int(pilot.get("level") or 1),
            "faction_id": int(pilot.get("factionId") or 0),
            "ship": str(ship.get("typeId") or ""),
            "credits": int(pilot.get("credits") or 0),
            "uridium": int(pilot.get("uridium") or 0),
            "ep": int(pilot.get("ep") or 0),
            "honour": int(pilot.get("honourPoints") or 0),
        }


def dispatch_snapshot(person, now=None):
    """Return gate state for an online or offline profile without mutating it."""
    import dispatch as DSP
    import kapi as KAPI

    now = time.time() if now is None else float(now)
    profile = person.profil
    # Reuse the live session systems when available. Offline profiles use the
    # same domain classes over their persisted state, but remain read-only here.
    if person.oturum is not None:
        dispatch = person.oturum.dispatch
        gates = person.oturum.kapilar
    else:
        gates = KAPI.Kapilar(profile)
        dispatch = DSP.Dispatch(profile, gates)

    rows = []
    with profile.lock:
        sent = dispatch.st.get("kapilar", {})
        for key in dispatch.gate_keys():
            definition = KAPI.KAPI[key]
            state = gates.gate(key)
            is_built = gates.built(key)
            until = sent.get(key)
            eligibility = gate_status(
                built=is_built,
                completed=int(state.get("tamam") or 0) > 0,
                wave=state.get("dalga", 0),
                sent_until=until,
                now=now,
            )
            rows.append({
                "key": key,
                "name": definition.get("ad", key),
                "gate_id": int(definition["kimlik"]),
                "parts": len(state.get("parcalar") or []),
                "required": int(definition["parca"]),
                "built": is_built,
                "prepared": bool(state.get("hazir")),
                "wave": int(state.get("dalga") or 0),
                "completed": int(state.get("tamam") or 0),
                "dispatch_until": int(until) if until is not None else None,
                **eligibility,
            })
    return rows
