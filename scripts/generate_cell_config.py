#!/usr/bin/env python3
"""Generate the minimal packaged-flow configuration from SPICE subcircuits."""

import argparse
import itertools
import json
import os
import re
from pathlib import Path


SUBCKT_START = re.compile(r"^\s*\.subckt\s+(\S+)(.*)$", re.I)
SUBCKT_END = re.compile(r"^\s*\.ends(?:\s+(\S+))?", re.I)


def safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_").lower()


def normalize_net(value: str) -> str:
    return value.lower()


def model_polarity(model: str):
    normalized = model.lower()
    if "pmos" in normalized or "pfet" in normalized:
        return "pmos"
    if "nmos" in normalized or "nfet" in normalized:
        return "nmos"
    return None


def parse_mos_devices(lines: list, path: Path, cell_name: str) -> list:
    statements = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if raw.lstrip().startswith("+"):
            if statements:
                statements[-1] += " " + raw.lstrip()[1:].strip()
            continue
        statements.append(raw.split("$", 1)[0].strip())

    devices = []
    for statement in statements:
        fields = statement.split()
        if not fields:
            continue
        designator = fields[0][0].lower()
        if designator != "m":
            if designator != ".":
                raise ValueError(
                    f"{path}: unsupported non-MOS instance in {cell_name}: {fields[0]}"
                )
            continue
        if len(fields) < 6:
            raise ValueError(f"{path}: malformed MOS instance in {cell_name}: {statement}")
        polarity = model_polarity(fields[5])
        if polarity is None:
            raise ValueError(
                f"{path}: cannot infer NMOS/PMOS polarity from model {fields[5]} "
                f"in {fields[0]}"
            )
        devices.append(
            {
                "name": fields[0],
                "drain": normalize_net(fields[1]),
                "gate": normalize_net(fields[2]),
                "source": normalize_net(fields[3]),
                "bulk": normalize_net(fields[4]),
                "model": fields[5],
                "polarity": polarity,
            }
        )
    if not devices:
        raise ValueError(f"{path}: {cell_name} contains no MOS instances")
    return devices


def parse_subckts(path: Path) -> list:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    result = []
    index = 0
    while index < len(lines):
        match = SUBCKT_START.match(lines[index])
        if not match:
            index += 1
            continue
        name = match.group(1)
        header = match.group(2).strip()
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].lstrip().startswith("+"):
            header += " " + lines[cursor].lstrip()[1:].strip()
            cursor += 1
        pins = header.split()
        end = cursor
        while end < len(lines):
            end_match = SUBCKT_END.match(lines[end])
            if end_match:
                end_name = end_match.group(1)
                if not end_name or end_name.lower() == name.lower():
                    break
            end += 1
        if end >= len(lines):
            raise SystemExit(f"{path}: SUBCKT {name} has no matching .ENDS")
        try:
            devices = parse_mos_devices(lines[cursor:end], path, name)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        result.append(
            {
                "cell_name": name,
                "pins": pins,
                "source_spice": path,
                "devices": devices,
            }
        )
        index = end + 1
    if not result:
        raise SystemExit(f"{path}: no .SUBCKT found")
    return result


def connected_components(devices: list, values: dict) -> dict:
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for device in devices:
        gate_value = values[device["gate"]]
        is_on = (
            device["polarity"] == "nmos" and gate_value == 1
        ) or (
            device["polarity"] == "pmos" and gate_value == 0
        )
        find(device["drain"])
        find(device["source"])
        if is_on:
            union(device["drain"], device["source"])
    return {node: find(node) for node in parent}


def truth_table_from_topology(
    cell_name: str,
    devices: list,
    inputs: list,
    output: str,
    power_pin: str,
    ground_pin: str,
) -> dict:
    input_nets = [normalize_net(pin) for pin in inputs]
    output_net = normalize_net(output)
    power_net = normalize_net(power_pin)
    ground_net = normalize_net(ground_pin)
    gate_nets = {device["gate"] for device in devices}
    internal_controls = sorted(
        gate_nets - set(input_nets) - {power_net, ground_net}
    )
    diffusion_nets = {
        net
        for device in devices
        for net in (device["drain"], device["source"])
    }
    undriven_controls = [
        net for net in internal_controls if net not in diffusion_nets
    ]
    if undriven_controls:
        raise ValueError(
            f"{cell_name}: internal MOS gates are not driven by a diffusion network: "
            f"{undriven_controls}"
        )
    if output_net in internal_controls:
        raise ValueError(
            f"{cell_name}: output {output} also controls an internal MOS gate; "
            "feedback/output-fed topology is unsupported"
        )

    table = {}
    for input_bits in itertools.product((0, 1), repeat=len(input_nets)):
        fixed_values = {
            power_net: 1,
            ground_net: 0,
            **dict(zip(input_nets, input_bits)),
        }
        stable_solutions = []
        for control_bits in itertools.product((0, 1), repeat=len(internal_controls)):
            values = {**fixed_values, **dict(zip(internal_controls, control_bits))}
            components = connected_components(devices, values)

            if components.get(power_net) == components.get(ground_net):
                continue

            controls_are_stable = True
            for net in internal_controls:
                component = components.get(net)
                if component == components.get(power_net):
                    resolved = 1
                elif component == components.get(ground_net):
                    resolved = 0
                else:
                    controls_are_stable = False
                    break
                if values[net] != resolved:
                    controls_are_stable = False
                    break
            if not controls_are_stable:
                continue

            output_component = components.get(output_net)
            if output_component == components.get(power_net):
                output_value = 1
            elif output_component == components.get(ground_net):
                output_value = 0
            else:
                continue
            stable_solutions.append((control_bits, output_value))

        vector = "".join(str(bit) for bit in input_bits)
        if len(stable_solutions) != 1:
            raise ValueError(
                f"{cell_name}: input vector {vector or '<none>'} has "
                f"{len(stable_solutions)} stable topology solutions; expected exactly one"
            )
        table[vector] = stable_solutions[0][1]
    return table


def boolean_function(inputs: list, truth_table: dict) -> str:
    asserted = [bits for bits, value in truth_table.items() if value == 1]
    if not asserted:
        return "0"
    if len(asserted) == len(truth_table):
        return "1"
    terms = []
    for bits in asserted:
        literals = [
            pin if bit == "1" else f"!{pin}"
            for pin, bit in zip(inputs, bits)
        ]
        terms.append("(" + " * ".join(literals) + ")")
    return " + ".join(terms)


def infer_logical_interface(cell: dict) -> dict:
    name = cell["cell_name"]
    pins = cell["pins"]
    devices = cell["devices"]
    normalized_pins = [normalize_net(pin) for pin in pins]
    if len(normalized_pins) != len(set(normalized_pins)):
        raise ValueError(f"{name}: duplicate SUBCKT pins are not supported")
    actual_pin = dict(zip(normalized_pins, pins))

    pmos_devices = [device for device in devices if device["polarity"] == "pmos"]
    nmos_devices = [device for device in devices if device["polarity"] == "nmos"]
    if not pmos_devices or not nmos_devices:
        raise ValueError(f"{name}: both PMOS and NMOS devices are required")

    pmos_bulks = {device["bulk"] for device in pmos_devices}
    nmos_bulks = {device["bulk"] for device in nmos_devices}
    if len(pmos_bulks) != 1 or len(nmos_bulks) != 1:
        raise ValueError(
            f"{name}: expected one common PMOS bulk and one common NMOS bulk; "
            f"found PMOS={sorted(pmos_bulks)}, NMOS={sorted(nmos_bulks)}"
        )
    power_net = next(iter(pmos_bulks))
    ground_net = next(iter(nmos_bulks))
    if power_net == ground_net:
        raise ValueError(f"{name}: PMOS and NMOS bulk networks are identical")
    if power_net not in actual_pin or ground_net not in actual_pin:
        raise ValueError(
            f"{name}: inferred power/ground must both be SUBCKT pins; "
            f"found power={power_net}, ground={ground_net}"
        )

    gate_nets = {device["gate"] for device in devices}
    pmos_diffusion = {
        net
        for device in pmos_devices
        for net in (device["drain"], device["source"])
    }
    nmos_diffusion = {
        net
        for device in nmos_devices
        for net in (device["drain"], device["source"])
    }
    diffusion_nets = pmos_diffusion | nmos_diffusion
    functional_pins = [
        pin
        for pin in pins
        if normalize_net(pin) not in {power_net, ground_net}
    ]
    output_candidates = [
        pin for pin in functional_pins if normalize_net(pin) in diffusion_nets
    ]
    if len(output_candidates) != 1:
        raise ValueError(
            f"{name}: expected exactly one external diffusion/output pin; "
            f"found {output_candidates}"
        )
    output = output_candidates[0]
    output_net = normalize_net(output)
    if output_net not in pmos_diffusion or output_net not in nmos_diffusion:
        raise ValueError(
            f"{name}: output {output} must connect to both PMOS and NMOS networks"
        )

    inputs = [pin for pin in functional_pins if pin != output]
    invalid_inputs = [
        pin
        for pin in inputs
        if normalize_net(pin) not in gate_nets
        or normalize_net(pin) in diffusion_nets
    ]
    if invalid_inputs:
        raise ValueError(
            f"{name}: inputs must drive MOS gates only; invalid pins={invalid_inputs}"
        )

    power_pin = actual_pin[power_net]
    ground_pin = actual_pin[ground_net]
    truth_table = truth_table_from_topology(
        name, devices, inputs, output, power_pin, ground_pin
    )
    return {
        "cell_name": name,
        "pins": pins,
        "source_spice": cell["source_spice"],
        "inputs": inputs,
        "output": output,
        "power_pin": power_pin,
        "ground_pin": ground_pin,
        "nmos_models": sorted({device["model"] for device in nmos_devices}),
        "pmos_models": sorted({device["model"] for device in pmos_devices}),
        "truth_table": truth_table,
        "function": boolean_function(inputs, truth_table),
    }


def relative_or_absolute(path: Path, output_dir: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), output_dir.resolve())
    except ValueError:
        return str(path.resolve())


def find_gds(gds_dir: Path, cell_name: str) -> Path:
    matches = [
        path
        for path in gds_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".gds", ".gds2"}
        and path.stem.lower() == cell_name.lower()
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{cell_name}: expected one matching GDS/GDS2 under {gds_dir}, found {matches}"
        )
    return matches[0]


def discover_spice(inputs: list, recursive: bool) -> list:
    result = []
    suffixes = {".sp", ".spi", ".spice", ".cdl", ".netlist"}
    for raw in inputs:
        path = raw.resolve()
        if path.is_file():
            result.append(path)
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            result.extend(
                child.resolve()
                for child in iterator
                if child.is_file() and child.suffix.lower() in suffixes
            )
        else:
            raise SystemExit(f"input does not exist: {path}")
    return sorted(set(result))


def assets(mode: str) -> dict:
    result = {
        "rule_dir": "${KLIB_ASSET_ROOT}/ruledirs",
        "pex_rule_template": "${KLIB_ASSET_ROOT}/reference/pex.rule",
        "model": "${KLIB_ASSET_ROOT}/models/7nm_TT_160803.pm",
        "liberate_settings": "${KLIB_ASSET_ROOT}/reference/settings.tcl",
        "area_tool": "${KLIB_ASSET_ROOT}/scripts/calc_lib_area.py",
    }
    if mode == "spice":
        result = {
            "stdgen_bin": "${KLIB_ASSET_ROOT}/tools/StdGen/StdGen",
            "stdgen_libs": "${KLIB_ASSET_ROOT}/tools/StdGen/libs",
            **result,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate cell configuration without build_manifest.py"
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="SPICE/CDL files or directories")
    parser.add_argument("--mode", choices=("spice", "gds"), required=True)
    parser.add_argument("--gds-dir", type=Path, help="Required in gds mode")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library-name", default="MY_ASAP7_POSTLAYOUT")
    parser.add_argument("--output-lib", default="my_asap7_postlayout.lib")
    parser.add_argument("--voltage", type=float, default=0.7)
    parser.add_argument("--temperature", type=float, default=25)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument(
        "--cell",
        action="append",
        default=[],
        help="Only include this SUBCKT name; may be repeated",
    )
    parser.add_argument(
        "--skip-unsupported",
        action="store_true",
        help="Skip subcircuits whose MOS topology cannot be inferred",
    )
    args = parser.parse_args()

    if args.mode == "gds" and args.gds_dir is None:
        parser.error("--gds-dir is required in gds mode")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    selected_names = {name.lower() for name in args.cell}
    cells = []
    errors = []
    for spice in discover_spice(args.inputs, args.recursive):
        for raw_cell in parse_subckts(spice):
            if selected_names and raw_cell["cell_name"].lower() not in selected_names:
                continue
            try:
                cell = infer_logical_interface(raw_cell)
                entry = {
                    "key": safe_key(cell["cell_name"]),
                    "cell_name": cell["cell_name"],
                    "source_spice": relative_or_absolute(spice, output.parent),
                    "inputs": cell["inputs"],
                    "output": cell["output"],
                    "power_pin": cell["power_pin"],
                    "ground_pin": cell["ground_pin"],
                    "nmos_models": cell["nmos_models"],
                    "pmos_models": cell["pmos_models"],
                    "pins": cell["pins"],
                    "truth_table": cell["truth_table"],
                    "function": cell["function"],
                }
                if args.mode == "gds":
                    gds = find_gds(args.gds_dir.resolve(), cell["cell_name"])
                    entry["gds"] = relative_or_absolute(gds, output.parent)
                cells.append(entry)
            except ValueError as exc:
                if args.skip_unsupported:
                    errors.append(str(exc))
                    continue
                raise SystemExit(str(exc)) from exc

    if not cells:
        raise SystemExit("no supported cells selected")
    names = [cell["cell_name"].lower() for cell in cells]
    if len(names) != len(set(names)):
        raise SystemExit("duplicate SUBCKT names were discovered")
    if selected_names:
        missing = sorted(selected_names - set(names))
        if missing:
            raise SystemExit(f"requested cells not found or unsupported: {missing}")

    config = {
        "library_name": args.library_name,
        "output_lib": args.output_lib,
        "voltage": args.voltage,
        "temperature": args.temperature,
        "threads": args.threads,
        "assets": assets(args.mode),
        "cells": cells,
    }
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}: {len(cells)} cells")
    for warning in errors:
        print(f"skipped: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
