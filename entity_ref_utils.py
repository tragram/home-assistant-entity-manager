#!/usr/bin/env python3
"""
Entity Reference Utilities - Zentrale, wortgrenzen-sichere Ersetzung von Entity-IDs.

Wird von dependency_updater.py und lovelace_updater.py
gemeinsam genutzt, damit die Ersetzungslogik nur an einer Stelle lebt.

Wichtig fuer den Geraete-Austausch: alte und neue entity_id haben voellig
unterschiedliche slugs (z.B. binary_sensor.kuche_fenster_tur ->
binary_sensor.kuche_fenster_neu_zustand). Eine reine Substring-Ersetzung wuerde
z.B. `..._tur` faelschlich in `..._tur_2` treffen. Daher:

- Direkte Werte / Listenelemente: nur bei EXAKTER Gleichheit ersetzen.
- Template-Strings ({{ ... }}): per Regex mit Wortgrenzen (\\b) ersetzen.
- Normale Freitext-Strings (kein Template): unangetastet lassen.
"""

import re
from collections.abc import Mapping
from typing import Any, Tuple


class EntityReferenceConflict(ValueError):
    """Raised when a rename would overwrite an existing dictionary key."""

_ENTITY_ID_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")


def extract_entity_ids(data: Any) -> set:
    """Sammelt rekursiv alle Strings, die wie eine entity_id (domain.object_id) aussehen.

    Bewusst grob (auch in Freitext/Templates) - dient nur dem in-use-Check (kommt eine
    konkrete entity_id irgendwo vor?), nicht der exakten Referenz-Klassifizierung.
    """
    found: set = set()

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            for m in _ENTITY_ID_RE.findall(node):
                found.add(m)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(data)
    return found


def replace_entity_ref_in_string(
    value: str,
    old_entity_id: str,
    new_entity_id: str,
    replace_embedded: bool = False,
) -> Tuple[str, bool]:
    """Ersetzt eine Entity-ID in einem einzelnen String.

    Args:
        value: Der zu pruefende String.
        old_entity_id: Die zu ersetzende Entity-ID.
        new_entity_id: Die neue Entity-ID.

    Returns:
        Tupel (neuer_string, wurde_geaendert).
    """
    if old_entity_id == new_entity_id:
        return value, False

    # Exakter Wert (z.B. entity_id: "light.kueche")
    if value == old_entity_id:
        return new_entity_id, True

    # Templates: Entity-ID kann als Teil eines Jinja-Ausdrucks vorkommen.
    # Nur mit Wortgrenzen ersetzen, damit `sensor.temp` nicht in
    # `sensor.temperature` trifft.
    has_jinja = ("{{" in value and "}}" in value) or ("{%" in value and "%}" in value)
    if has_jinja and old_entity_id in value:
        pattern = r"\b" + re.escape(old_entity_id) + r"\b"
        new_value = re.sub(pattern, new_entity_id, value)
        if new_value != value:
            return new_value, True

    # Custom dashboard cards often embed entity IDs in JavaScript or CSS
    # expressions. Keep token boundaries so similarly named IDs are untouched.
    if replace_embedded and old_entity_id in value:
        pattern = rf"(?<![a-z0-9_]){re.escape(old_entity_id)}(?![a-z0-9_])"
        new_value = re.sub(pattern, new_entity_id, value)
        if new_value != value:
            return new_value, True

    return value, False


def replace_entity_refs_in_string(
    value: str,
    replacements: Mapping[str, str],
    replace_embedded: bool = False,
) -> Tuple[str, bool]:
    """Replace multiple IDs simultaneously, without rename-chain cascading."""
    replacements = {old: new for old, new in replacements.items() if old != new}
    if not replacements:
        return value, False
    if value in replacements:
        return replacements[value], True

    has_jinja = ("{{" in value and "}}" in value) or ("{%" in value and "%}" in value)
    if has_jinja:
        updated = _ENTITY_ID_RE.sub(lambda match: replacements.get(match.group(1), match.group(1)), value)
        if updated != value:
            return updated, True

    if replace_embedded:
        alternatives = "|".join(re.escape(entity_id) for entity_id in sorted(replacements, key=len, reverse=True))
        pattern = re.compile(rf"(?<![a-z0-9_])(?:{alternatives})(?![a-z0-9_])")
        updated = pattern.sub(lambda match: replacements.get(match.group(0), match.group(0)), value)
        if updated != value:
            return updated, True
    return value, False


def replace_entities_in_obj(
    data: Any,
    replacements: Mapping[str, str],
    replace_embedded: bool = False,
) -> bool:
    """Apply a complete rename map recursively and atomically in-place.

    Dictionary keys are planned as a set before mutation, so swaps and chains
    retain every value while true many-to-one collisions are rejected.
    """
    replacements = {old: new for old, new in replacements.items() if old != new}
    if not replacements:
        return False
    changed = False

    if isinstance(data, dict):
        remapped: dict[Any, Any] = {}
        original_for_target: dict[Any, Any] = {}
        keys_changed = False
        for key, value in data.items():
            target = replacements.get(key, key) if isinstance(key, str) else key
            if target in remapped:
                previous = original_for_target[target]
                raise EntityReferenceConflict(
                    f"Cannot replace entity references: {previous} and {key} both target {target}"
                )
            remapped[target] = value
            original_for_target[target] = key
            keys_changed = keys_changed or target != key
        if keys_changed:
            data.clear()
            data.update(remapped)
            changed = True

        for key, value in list(data.items()):
            if isinstance(value, str):
                updated, did_change = replace_entity_refs_in_string(value, replacements, replace_embedded)
                if did_change:
                    data[key] = updated
                    changed = True
            elif isinstance(value, (dict, list)):
                changed = replace_entities_in_obj(value, replacements, replace_embedded) or changed

    elif isinstance(data, list):
        for index, value in enumerate(data):
            if isinstance(value, str):
                updated, did_change = replace_entity_refs_in_string(value, replacements, replace_embedded)
                if did_change:
                    data[index] = updated
                    changed = True
            elif isinstance(value, (dict, list)):
                changed = replace_entities_in_obj(value, replacements, replace_embedded) or changed
    return changed


def replace_entity_in_obj(
    data: Any,
    old_entity_id: str,
    new_entity_id: str,
    replace_embedded: bool = False,
) -> bool:
    """Ersetzt eine Entity-ID rekursiv in einer beliebigen Datenstruktur (in-place).

    Behandelt Strings (exakt oder Template), Listen und verschachtelte Dicts/Listen.

    Args:
        data: dict, list oder beliebiger Wert (wird in-place mutiert).
        old_entity_id: Die zu ersetzende Entity-ID.
        new_entity_id: Die neue Entity-ID.

    Returns:
        True, wenn irgendwo etwas geaendert wurde.
    """
    return replace_entities_in_obj(data, {old_entity_id: new_entity_id}, replace_embedded)
