#!/usr/bin/env python3
"""Calculate Liberty cell area from a GDS cell width.

ASAP7 6-track cells use a fixed cell height of 0.216 um.  This script measures
the GDS width from non-text geometry only, so pin labels placed outside the cell
do not affect the computed Liberty area.
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GDS_DIR = SCRIPT_DIR / "gds"
DEFAULT_LIB_DIR = SCRIPT_DIR / "liberate"
DEFAULT_CELL_HEIGHT_UM = 0.216
KLAYOUT_BIN = "klayout"
BOUNDARY_LAYER_KEYS = [(100, 0, 8), (98, 0, 8)]


KLAYOUT_HELPER = r'''
import json
import os
import sys
import pya


def main():
    gds_path = os.environ["GDS_PATH"]
    requested_cell = os.environ.get("CELL_NAME", "")

    layout = pya.Layout()
    layout.read(gds_path)

    cell = layout.cell(requested_cell) if requested_cell else None
    if cell is None:
        cell = layout.top_cell()
    if cell is None:
        raise RuntimeError("GDS has no top cell")

    bbox = None
    text_count = 0
    geometry_count = 0
    for layer_index in layout.layer_indices():
        iterator = cell.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            shape = iterator.shape()
            if shape.is_text():
                text_count += 1
                iterator.next()
                continue

            shape_bbox = shape.bbox()
            if not shape_bbox.empty():
                geometry_count += 1
                transformed_bbox = shape_bbox.transformed(iterator.trans())
                bbox = transformed_bbox if bbox is None else bbox + transformed_bbox
            iterator.next()

    if bbox is None or bbox.empty():
        raise RuntimeError("No non-text geometry found in selected cell")

    dbu = layout.dbu
    width_um = bbox.width() * dbu
    height_um = bbox.height() * dbu
    print(
        "__AREA_JSON__"
        + json.dumps(
            {
                "top_cell": cell.name,
                "dbu": dbu,
                "bbox_dbu": {
                    "left": bbox.left,
                    "right": bbox.right,
                    "bottom": bbox.bottom,
                    "top": bbox.top,
                },
                "width_um": width_um,
                "geometry_bbox_height_um": height_um,
                "geometry_count": geometry_count,
                "text_count_ignored": text_count,
            },
            sort_keys=True,
        )
    )


main()
'''


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Measure a circuit GDS width excluding text labels and compute "
            "Liberty area as width * ASAP7 cell height."
        )
    )
    parser.add_argument("circuit", help="Circuit/cell name, for example FULLADDER or COMP42.")
    parser.add_argument(
        "--gds-dir",
        type=Path,
        default=DEFAULT_GDS_DIR,
        help=f"GDS directory. Default: {DEFAULT_GDS_DIR}",
    )
    parser.add_argument(
        "--lib-dir",
        type=Path,
        default=DEFAULT_LIB_DIR,
        help=f"Liberty directory. Default: {DEFAULT_LIB_DIR}",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=DEFAULT_CELL_HEIGHT_UM,
        help=f"ASAP7 standard-cell height in um. Default: {DEFAULT_CELL_HEIGHT_UM}",
    )
    parser.add_argument(
        "--cell",
        help="Cell name inside the GDS. Default: same as circuit; falls back to the GDS top cell.",
    )
    parser.add_argument(
        "--gds",
        type=Path,
        help="Explicit GDS path. Default: search <gds-dir>/<circuit>.gds/.gds2.",
    )
    parser.add_argument(
        "--lib",
        type=Path,
        help="Explicit Liberty path for --update-lib. Default: <lib-dir>/<circuit>.lib.",
    )
    parser.add_argument(
        "--update-lib",
        action="store_true",
        help="Replace the cell's area value in the Liberty file.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=6,
        help="Decimal places for printed and written area. Default: 6.",
    )
    parser.add_argument(
        "--area-engine",
        choices=["auto", "klayout", "python"],
        default="auto",
        help="Area measurement engine. Default: auto.",
    )
    parser.add_argument(
        "--debug-layers",
        action="store_true",
        help="With the Python engine, print per-layer GDS bounding boxes.",
    )
    return parser.parse_args()


def find_gds(circuit, gds_dir, explicit_gds):
    if explicit_gds is not None:
        path = explicit_gds.expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"GDS file does not exist: {path}")
        return path

    candidates = [
        gds_dir / f"{circuit}.gds",
        gds_dir / f"{circuit}.gds2",
        gds_dir / f"{circuit.upper()}.gds",
        gds_dir / f"{circuit.upper()}.gds2",
        gds_dir / f"{circuit.lower()}.gds",
        gds_dir / f"{circuit.lower()}.gds2",
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()

    matches = sorted(
        path for path in gds_dir.glob("*") if path.suffix.lower() in {".gds", ".gds2"} and path.stem.lower() == circuit.lower()
    )
    if matches:
        return matches[0].resolve()

    raise SystemExit(f"Could not find GDS for {circuit} under {gds_dir}")


def run_klayout_measurement(gds_path, cell_name):
    helper_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as helper:
            helper.write(KLAYOUT_HELPER)
            helper_path = Path(helper.name)

        env = os.environ.copy()
        env["GDS_PATH"] = str(gds_path)
        env["CELL_NAME"] = cell_name
        completed = subprocess.run(
            [KLAYOUT_BIN, "-b", "-r", str(helper_path)],
            check=True,
            universal_newlines=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Could not run {KLAYOUT_BIN}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout)
        sys.stderr.write(exc.stderr)
        raise SystemExit(f"KLayout failed while reading {gds_path}") from exc
    finally:
        if helper_path is not None:
            try:
                helper_path.unlink()
            except FileNotFoundError:
                pass

    for line in completed.stdout.splitlines():
        if line.startswith("__AREA_JSON__"):
            return json.loads(line[len("__AREA_JSON__") :])

    sys.stderr.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    raise SystemExit("KLayout did not return measurement JSON")


def decode_gds_real8(raw):
    if len(raw) != 8:
        raise ValueError("GDS real8 must be 8 bytes")
    first = raw[0]
    if first == 0 and raw == b"\x00" * 8:
        return 0.0
    sign = -1.0 if (first & 0x80) else 1.0
    exponent = (first & 0x7F) - 64
    mantissa = 0
    for byte in raw[1:]:
        mantissa = (mantissa << 8) | byte
    return sign * (mantissa / float(1 << 56)) * (16.0 ** exponent)


def gds_string(data):
    return data.rstrip(b"\0").decode("ascii", "ignore")


def gds_int4_list(data):
    count = len(data) // 4
    if count == 0:
        return []
    return list(struct.unpack(">" + "i" * count, data[: count * 4]))


def bbox_from_xy(xy, path_width=0):
    if len(xy) < 4:
        return None
    xs = xy[0::2]
    ys = xy[1::2]
    expand = abs(path_width) // 2 if path_width else 0
    return {
        "left": min(xs) - expand,
        "right": max(xs) + expand,
        "bottom": min(ys) - expand,
        "top": max(ys) + expand,
    }


def merge_bbox(a, b):
    if a is None:
        return dict(b)
    return {
        "left": min(a["left"], b["left"]),
        "right": max(a["right"], b["right"]),
        "bottom": min(a["bottom"], b["bottom"]),
        "top": max(a["top"], b["top"]),
    }


def parse_gds_measurement(gds_path, cell_name, debug_layers=False):
    data = gds_path.read_bytes()
    offset = 0
    dbu_um = None
    current_cell = None
    current_element = None
    current_layer = None
    current_datatype = None
    current_width = 0
    current_xy = None
    cells = {}
    referenced = set()

    while offset + 4 <= len(data):
        length, record_type, data_type = struct.unpack(">HBB", data[offset : offset + 4])
        if length < 4 or offset + length > len(data):
            raise SystemExit("Invalid GDS record while reading {}".format(gds_path))
        payload = data[offset + 4 : offset + length]
        offset += length

        if record_type == 0x03 and len(payload) >= 16:
            # UNITS: second real is database-unit size in meters.
            dbu_um = decode_gds_real8(payload[8:16]) * 1e6
        elif record_type == 0x05:
            current_cell = {
                "name": None,
                "bbox": None,
                "layer_bboxes": {},
                "geometry_count": 0,
                "text_count": 0,
            }
        elif record_type == 0x06 and current_cell is not None:
            current_cell["name"] = gds_string(payload)
        elif record_type == 0x07 and current_cell is not None:
            if current_cell["name"]:
                cells[current_cell["name"]] = current_cell
            current_cell = None
        elif record_type in (0x08, 0x09, 0x2D, 0x0C):
            current_element = record_type
            current_layer = None
            current_datatype = None
            current_width = 0
            current_xy = None
        elif record_type == 0x0A:
            current_element = record_type
            current_layer = None
            current_datatype = None
            current_width = 0
            current_xy = None
        elif record_type == 0x0B:
            current_element = record_type
            current_layer = None
            current_datatype = None
            current_width = 0
            current_xy = None
        elif record_type == 0x0D and len(payload) >= 2:
            current_layer = struct.unpack(">h", payload[:2])[0]
        elif record_type in (0x0E, 0x16) and len(payload) >= 2:
            current_datatype = struct.unpack(">h", payload[:2])[0]
        elif record_type == 0x0F:
            values = gds_int4_list(payload)
            current_width = values[0] if values else 0
        elif record_type == 0x10:
            current_xy = gds_int4_list(payload)
        elif record_type == 0x12:
            referenced.add(gds_string(payload))
        elif record_type == 0x11 and current_cell is not None:
            if current_element == 0x0C:
                current_cell["text_count"] += 1
            elif current_element in (0x08, 0x09, 0x2D):
                box = bbox_from_xy(current_xy or [], current_width if current_element == 0x09 else 0)
                if box is not None:
                    key = (current_layer, current_datatype, current_element)
                    current_cell["bbox"] = merge_bbox(current_cell["bbox"], box)
                    current_cell["layer_bboxes"][key] = merge_bbox(
                        current_cell["layer_bboxes"].get(key), box
                    )
                    current_cell["geometry_count"] += 1
            current_element = None
            current_layer = None
            current_datatype = None
            current_width = 0
            current_xy = None

    if dbu_um is None:
        raise SystemExit("Could not read GDS units from {}".format(gds_path))

    cell = cells.get(cell_name)
    if cell is None:
        top_names = [name for name in cells if name not in referenced]
        fallback_name = top_names[0] if top_names else (list(cells.keys())[0] if cells else None)
        cell = cells.get(fallback_name) if fallback_name else None
    if cell is None:
        raise SystemExit("GDS has no readable cells: {}".format(gds_path))
    bbox_source = "all-non-text"
    bbox = cell["bbox"]
    for key in BOUNDARY_LAYER_KEYS:
        if key in cell["layer_bboxes"]:
            bbox = cell["layer_bboxes"][key]
            bbox_source = "boundary-layer-{}-{}".format(key[0], key[1])
            break

    if bbox is None:
        raise SystemExit("No non-text geometry found in selected cell")

    if debug_layers:
        sys.stderr.write("GDS layer bboxes for {}:\n".format(cell["name"]))
        for key, layer_bbox in sorted(
            cell["layer_bboxes"].items(),
            key=lambda item: ((item[1]["right"] - item[1]["left"]), item[0]),
        ):
            width = (layer_bbox["right"] - layer_bbox["left"]) * dbu_um
            height = (layer_bbox["top"] - layer_bbox["bottom"]) * dbu_um
            sys.stderr.write(
                "  layer={} datatype={} elem={} width_um={:.6f} height_um={:.6f} bbox={}\n".format(
                    key[0], key[1], key[2], width, height, layer_bbox
                )
            )

    width_um = (bbox["right"] - bbox["left"]) * dbu_um
    height_um = (bbox["top"] - bbox["bottom"]) * dbu_um
    return {
        "top_cell": cell["name"],
        "dbu": dbu_um,
        "bbox_dbu": bbox,
        "width_um": width_um,
        "geometry_bbox_height_um": height_um,
        "geometry_count": cell["geometry_count"],
        "text_count_ignored": cell["text_count"],
        "area_engine": "python-gds",
        "bbox_source": bbox_source,
    }


def measure_area(gds_path, cell_name, area_engine, debug_layers=False):
    if area_engine == "python":
        return parse_gds_measurement(gds_path, cell_name, debug_layers)
    if area_engine == "klayout":
        return run_klayout_measurement(gds_path, cell_name)
    if shutil.which(KLAYOUT_BIN):
        return run_klayout_measurement(gds_path, cell_name)
    return parse_gds_measurement(gds_path, cell_name, debug_layers)


def update_lib_area(lib_path, cell_name, area_text):
    if not lib_path.exists():
        raise SystemExit(f"Liberty file does not exist: {lib_path}")

    text = lib_path.read_text(encoding="utf-8")
    cell_pattern = re.compile(r"(?P<head>cell\s*\(\s*" + re.escape(cell_name) + r"\s*\)\s*\{)(?P<body>.*?)(?P<tail>\n\s*\})", re.S)
    match = cell_pattern.search(text)
    if match is None:
        raise SystemExit(f"Could not find cell ({cell_name}) in {lib_path}")

    body = match.group("body")
    new_body, replacements = re.subn(
        r"(\n\s*area\s*:\s*)[-+0-9.eE]+(\s*;)",
        rf"\g<1>{area_text}\2",
        body,
        count=1,
    )
    if replacements != 1:
        raise SystemExit(f"Could not find area attribute in cell ({cell_name})")

    updated = text[: match.start("body")] + new_body + text[match.end("body") :]
    lib_path.write_text(updated, encoding="utf-8")


def main():
    args = parse_args()
    circuit = args.circuit
    cell_name = args.cell or circuit
    gds_path = find_gds(circuit, args.gds_dir.expanduser(), args.gds)
    measurement = measure_area(gds_path, cell_name, args.area_engine, args.debug_layers)

    width_um = float(measurement["width_um"])
    area = width_um * args.height
    area_text = f"{area:.{args.precision}f}".rstrip("0").rstrip(".")

    print(f"circuit: {circuit}")
    print(f"gds: {gds_path}")
    print(f"gds_cell: {measurement['top_cell']}")
    print(f"non_text_bbox_width_um: {width_um:.{args.precision}f}")
    print(f"fixed_cell_height_um: {args.height:.{args.precision}f}")
    print(f"lib_area: {area_text}")
    print(f"area_engine: {measurement.get('area_engine', 'klayout')}")
    print(f"bbox_source: {measurement.get('bbox_source', 'all-non-text')}")
    print(f"text_labels_ignored: {measurement['text_count_ignored']}")

    if args.update_lib:
        lib_path = (args.lib or (args.lib_dir / f"{circuit}.lib")).expanduser().resolve()
        update_lib_area(lib_path, cell_name, area_text)
        print(f"updated_lib: {lib_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
