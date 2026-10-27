"""Read 3MF design intent only; never treat saved colors as verified tool mappings."""

import json
import re


def local(tag):
    return tag.rsplit("}", 1)[-1]


class ColorInspection:
    def __init__(self, read, names, root_path, settings):
        self.root_path = root_path
        self.settings = settings
        self.groups = {}
        self.palette = []
        self.references = {}
        self.used_objects = set()
        self.filaments = []
        self.reasons = set()
        self.painted = False
        if "Metadata/project_settings.config" in names:
            try:
                raw = read("Metadata/project_settings.config")
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError()
                data = json.loads(raw)
                colors = data.get("filament_colour", data.get("filament_color", []))
                types = data.get("filament_type", [])
                labels = data.get("filament_settings_id", [])
                if not all(isinstance(x, list) for x in (colors, types, labels)):
                    raise ValueError()
                count = max(len(colors), len(types), len(labels))
                if count > 64:
                    self.reasons.add("Saved filament list exceeds inspection limits.")
                for i in range(min(count, 64)):
                    color = self.color(colors[i]) if i < len(colors) else None
                    self.filaments.append(
                        dict(
                            slot=i + 1,
                            color=color,
                            material=str(types[i])[:80] if i < len(types) else None,
                            name=str(labels[i])[:100] if i < len(labels) else None,
                        )
                    )
            except (ValueError, TypeError, KeyError):
                self.reasons.add("Saved filament metadata could not be interpreted.")

    def color(self, value):
        if isinstance(value, str) and re.fullmatch(
            r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value
        ):
            return value.upper() + ("FF" if len(value) == 7 else "")
        if value:
            self.reasons.add("An unsupported saved color value needs review.")
        return None

    def document(self, name, resources):
        for group in resources:
            kind = local(group.tag)
            if kind not in (
                "basematerials",
                "colorgroup",
                "texture2dgroup",
                "multiproperties",
                "compositematerials",
            ):
                continue
            key = (name, group.get("id"))
            entries = []
            for index, entry in enumerate(group):
                if index >= 128:
                    self.reasons.add("Color resource exceeds inspection limits.")
                    break
                color = self.color(entry.get("color") or entry.get("displaycolor"))
                item = dict(
                    index=index, color=color, name=(entry.get("name") or "")[:100]
                )
                entries.append(item)
                if len(self.palette) < 128:
                    self.palette.append(
                        dict(resource_id=group.get("id"), kind=kind, **item)
                    )
            self.groups[key] = (kind, entries)

    def object(self, name, obj, faces):
        self.used_objects.add((name, obj.get("id")))
        if any(
            local(k) in ("paint_color", "mmu_segmentation", "color", "displaycolor")
            and v
            for k, v in obj.attrib.items()
        ):
            self.painted = True
        default_pid = obj.get("pid")
        default_index = obj.get("pindex")
        if not faces and default_pid is not None:
            self.reasons.add("Assembly-level color properties require mapping review.")
        # Only referenced geometry contributes to detection; unused resources do not.
        for face in faces:
            if any(
                local(k) in ("paint_color", "mmu_segmentation", "paint", "segmentation")
                and v
                for k, v in face.attrib.items()
            ):
                self.painted = True
            pid = face.get("pid", default_pid)
            if pid is None:
                if any(k in face.attrib for k in ("p1", "p2", "p3")):
                    self.reasons.add(
                        "Face properties have no resolvable material resource."
                    )
                continue
            indices = [
                face.get(k, face.get("p1", default_index)) for k in ("p1", "p2", "p3")
            ]
            for index in set(indices):
                key = (name, pid, index)
                if key in self.references:
                    self.references[key] += 1
                elif len(self.references) < 128:
                    self.references[key] = 1
                else:
                    self.reasons.add(
                        "Too many distinct face-property assignments to verify."
                    )

    def summary(self):
        assignments = []
        used_colors = set()
        used_slots = set()
        for (name, pid, index), count in self.references.items():
            group = self.groups.get((name, pid))
            color = None
            try:
                if not group or group[0] not in ("basematerials", "colorgroup"):
                    raise ValueError()
                item = group[1][int(index)]
                if int(index) < 0:
                    raise ValueError()
                color = item["color"]
                if color:
                    used_colors.add(color)
            except (ValueError, TypeError, IndexError):
                self.reasons.add(
                    "A referenced 3MF material, texture or color mapping is unresolved."
                )
            assignments.append(
                dict(
                    source="3MF face properties",
                    resource_id=str(pid)[:80],
                    property_index=str(index)[:80],
                    triangles=count,
                    color=color,
                    filament_slot=None,
                )
            )
        if self.references:
            self.reasons.add(
                "3MF face properties need verified physical filament mappings and multicolor slice results."
            )
        if self.settings is not None:
            for obj in self.settings.findall("object"):
                if (self.root_path, obj.get("id")) not in self.used_objects:
                    continue

                def slot(node):
                    values = [
                        x.get("value")
                        for x in node.findall("metadata")
                        if x.get("key") == "extruder"
                    ]
                    if not values:
                        return None
                    try:
                        if len(set(values)) != 1:
                            raise ValueError()
                        value = int(values[0])
                        if value <= 0 or value > len(self.filaments):
                            raise ValueError()
                        return value
                    except (ValueError, TypeError):
                        self.reasons.add(
                            "A saved object/part filament assignment is unresolved."
                        )
                        return None

                default = slot(obj)
                parts = obj.findall("part")
                for part in parts or [obj]:
                    value = slot(part) or default
                    if value:
                        used_slots.add(value)
                        if self.filaments[value - 1]["color"]:
                            used_colors.add(self.filaments[value - 1]["color"])
                        assignments.append(
                            dict(
                                source="Bambu object/part",
                                object_id=str(obj.get("id"))[:80],
                                part_id=str(part.get("id"))[:80],
                                filament_slot=value,
                                color=self.filaments[value - 1]["color"],
                            )
                        )
        if self.painted:
            self.reasons.add(
                "Painted face data detected; its encoded filament mapping and slice results are not verified."
            )
        if len(used_slots) > 1:
            self.reasons.add(
                "Multiple assigned filament slots require verified multicolor slicing."
            )
        if len(self.filaments) > 1 and not used_slots and not self.references:
            self.reasons.add(
                "Multiple saved filament slots exist but no verified model assignment was found."
            )
        if len(assignments) > 128:
            self.reasons.add(
                "Assignment display was truncated; review the original project."
            )
        exceeds_limit = len(used_slots) > 4 or len(used_colors) > 4
        if exceeds_limit:
            self.reasons.add(
                "This MVP supports at most four assigned colors/filament slots; this project exceeds that limit."
            )
        result = dict(
            max_supported_colors=4,
            assigned_color_count=None if self.painted else len(used_colors),
            exceeds_mvp_limit=exceeds_limit,
            saved_filaments=self.filaments,
            saved_palette=self.palette,
            assignments=assignments[:128],
            assigned_slots=sorted(used_slots),
            painted_faces_detected=self.painted,
            multicolor_detected=self.painted
            or len(used_slots) > 1
            or len(used_colors) > 1,
            quoting_blocked=bool(self.reasons),
            block_reasons=sorted(self.reasons),
            mappings_verified=False,
            slicer_results_verified=False,
            note="Saved file intent only. Slots listed in a palette are not proof that every slot is used. Colors and physical filament mappings are not applied by the geometry-only slicer.",
        )
        result["material_inference"] = infer_material(result)
        result["color_inference"] = infer_colors(result)
        return result


def color_name(color):
    """Broad display names for saved RGB colors, not manufacturer shade matches."""
    from colorsys import rgb_to_hsv

    code = color.lstrip("#")
    if len(code) not in (6, 8):
        return color
    try:
        r, g, b = (int(code[i:i + 2], 16) / 255 for i in (0, 2, 4))
        alpha = int(code[6:8], 16) if len(code) == 8 else 255
    except ValueError:
        return color
    hue, saturation, value = rgb_to_hsv(r, g, b)
    hue *= 360
    if value < 0.15:
        name = "Black"
    elif saturation < 0.12:
        name = "White" if value > 0.9 else "Gray"
    elif 15 <= hue < 50 and value < 0.65:
        name = "Brown"
    elif hue < 15 or hue >= 345:
        name = "Red"
    elif hue < 45:
        name = "Orange"
    elif hue < 70:
        name = "Yellow"
    elif hue < 165:
        name = "Green"
    elif hue < 195:
        name = "Cyan"
    elif hue < 255:
        name = "Blue"
    elif hue < 320:
        name = "Purple"
    else:
        name = "Pink"
    return ("Transparent " if alpha < 255 else "") + name


def infer_colors(info):
    saved = {f["slot"]: f.get("color") for f in info.get("saved_filaments", [])}
    assigned = [
        dict(slot=s, color=saved.get(s)) for s in info.get("assigned_slots", [])
    ]
    unresolved = (
        info.get("painted_faces_detected")
        or any(a.get("filament_slot") is None for a in info.get("assignments", []))
        or any("unresolved" in r.lower() for r in info.get("block_reasons", []))
    )
    result = dict(
        suggested_color=None,
        assigned_colors=assigned,
        status="needs_review",
        clarification="Confirm the requested color(s); no complete assigned color mapping was found.",
    )
    if (
        not unresolved
        and assigned
        and len(assigned) <= 4
        and all(a["color"] for a in assigned)
    ):
        colors = list(dict.fromkeys(a["color"] for a in assigned))

        result.update(
            suggested_color=" / ".join(color_name(c) for c in colors),
            status="suggested",
            clarification=None,
        )
    return result


def infer_material(info):
    from backend.filaments import TYPES

    slots = info.get("assigned_slots", [])
    saved = {f["slot"]: f.get("material") for f in info.get("saved_filaments", [])}
    values = sorted({str(saved.get(slot) or "").strip().upper() for slot in slots})
    result = dict(
        suggested_material=None,
        assigned_materials=[v for v in values if v],
        source="assigned_3mf_slots",
        status="missing_assignments",
        clarification="Which filament type should be used? No usable model-to-filament assignment was found in this 3MF.",
    )
    unresolved = (
        info.get("painted_faces_detected")
        or any(a.get("filament_slot") is None for a in info.get("assignments", []))
        or any("unresolved" in r.lower() for r in info.get("block_reasons", []))
    )
    if unresolved:
        result.update(
            status="unresolved_assignments",
            clarification="Which filament type should each assigned or painted region use? The saved mappings are unresolved.",
        )
    elif len(values) > 1:
        result.update(
            status="conflicting_materials",
            clarification="Assigned slots contain different filament types ("
            + ", ".join(v or "unspecified" for v in values)
            + "). Confirm the intended material for each slot; no single type can be assumed.",
        )
    elif slots and values and values[0] in TYPES:
        result.update(
            status="suggested", suggested_material=values[0], clarification=None
        )
    elif slots:
        result.update(
            status="unsupported_material",
            clarification="The assigned filament type is missing or not in the request catalog. Select the intended type for review; do not assume PLA.",
        )
    return result


def require_single_filament(job):
    from fastapi import HTTPException

    file = job.get("file") or {}
    info = file.get("color_info")
    if file.get("source_format") == "3mf" and info is None:
        raise HTTPException(
            422, "Re-upload this 3MF for color/mapping inspection before quoting."
        )
    if info and info.get("quoting_blocked"):
        raise HTTPException(
            422,
            "Multicolor or unresolved 3MF assignments require verified filament mappings and slicer results. Quoting is blocked; a manual estimate cannot bypass this check.",
        )
