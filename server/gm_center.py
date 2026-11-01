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
    """Return gate state for online or offline profiles without changing them."""
    import kapi as KAPI

    now = time.time() if now is None else float(now)
    profile = person.profil
    rows = []
    with profile.lock:
        # Read only persisted state. Do not instantiate Dispatch/Kapilar here:
        # their convenience properties initialize missing default dictionaries.
        gate_section = profile.d.get("kapilar") or {}
        gate_states = gate_section.get("kapilar") or {}
        dispatch_section = profile.d.get("dispatch") or {}
        sent = dispatch_section.get("kapilar") or {}

        for key, definition in KAPI.KAPI.items():
            if key == "hades":  # grup kapısı Dispatch ile gönderilmez
                continue
            state = gate_states.get(key) or KAPI.fresh(definition)
            # parcalar is the currently assembled gate. Once that gate is
            # prepared, new spins go to sonraki and must be shown separately.
            # GalaxyGateBuilderInfoCommand.currPart uses Kapilar.parts(), which
            # switches to sonraki while hazir=True; Dispatch.send_gate(), in
            # contrast, validates built() against parcalar.
            parts = len(state.get("parcalar") or [])
            next_parts = len(state.get("sonraki") or []) if state.get("hazir") else 0
            required = int(definition["parca"])
            is_built = parts >= required
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
                "parts": parts,
                "required": required,
                "built": is_built,
                "prepared": bool(state.get("hazir")),
                "next_parts": next_parts,
                "next_required": required,
                "next_built": next_parts >= required,
                "wave": int(state.get("dalga") or 0),
                "completed": int(state.get("tamam") or 0),
                "dispatch_until": int(until) if until is not None else None,
                **eligibility,
            })
    return rows
